from __future__ import annotations
import asyncio, json, os, re, time
from app.core.jsonutil import parse_json
from app.core.graph import validate_plan, ready_nodes
from app.core.security import redact_secrets
from app.core.types import Usage
from app.core.incidents import safe_provider_incident, safe_runtime_incident

PROMPT_VERSIONS={
 "analyzer":"ANL-2.1","planner":"PLN-2.0","worker":"WRK-2.0","verifier":"VRF-2.0","synth":"SYN-2.0","solver":"SOL-2.0"
}
ANALYZER_SYS="""You are the Structural Analyzer inside a research Adaptive Multi-Agent Orchestrator.
Return JSON only:
{
 "aspects":[{"name":"...", "goal":"..."}],
 "dependencies":[{"from":"aspect name","to":"aspect name","reason":"..."}],
 "parallelizable_groups":[["aspect name"]],
 "verification_demand":"low|medium|high",
 "verification_reasons":["..."],
 "rationale":"..."
}
Use only the task, frozen reference context, and observable structural signals.
Use one aspect for a straightforward single-fact lookup; do not create a
generic "parse/read the document" aspect. Add a dependency edge only when
one answer is an explicit prerequisite for another, not merely because two
topics are related. Put independent topical aspects in the same
parallelizable group. Mark verification demand high when the task contains
conflicts, exceptions, contrasting cases, or asks to avoid confusing a rule
with its exception. Return the fields above; do not invent labels or scoring
dimensions outside the schema."""
PLANNER_SYS="""You are a Planner Agent. Return JSON only:
{"subtasks":[{"id":"S1","goal":"...","depends_on":[]}]}
Create the smallest useful DAG for the task. Dependencies must represent real prerequisite relationships."""
VERIFIER_SYS="""You are the Runtime Verifier, not the research evaluator.
Using only original task, frozen context and candidate answer, return JSON only:
{"status":"PASS|NEEDS_WORK|FAIL","issues":[{"type":"missing|conflict|unsupported|format","description":"...","target":"..."}],"rationale":"..."}
PASS only when the candidate is sufficient for the user task. Do not use hidden rubrics."""
SOLVER_SYS="You are the Direct Solver. Answer the task using only the frozen reference context. Be concise and source-grounded."
WORKER_SYS="You are a Worker Agent. Solve only the assigned subtask using the frozen reference context. Return evidence-focused output."
SYNTH_SYS="You are the Synthesizer. Combine worker results into one answer to the original task. Do not invent facts outside frozen context."

PRICE_PER_MTOK={
 "gpt-5.6-sol":(4.00,20.00),
 "gpt-5.6-terra":(2.00,12.00),
 "gpt-5.6-luna":(0.20,1.20),
 "gemini-3.7-flash":(0.75,3.75),
 "gemini-3.6-flash":(0.75,3.75),
 "gemini-3.5-flash-lite":(0.30,2.50),
 "openai/gpt-oss-120b":(0.15,0.60),
 "openai/gpt-oss-20b":(0.075,0.30),
 "openrouter/free":(0.0,0.0),
}
# Groq reports cached-input usage separately when a prompt-cache hit is
# available. Keep this companion table separate so existing two-rate callers
# remain compatible.
CACHED_INPUT_PRICE_PER_MTOK={
 "openai/gpt-oss-120b":0.075,
 "openai/gpt-oss-20b":0.037,
}

# Versioned research identities. These are deliberately data-only: they do
# not contain provider credentials and are persisted with every run so a
# comparison can be reproduced/audited later.
CONFIG_VERSION="1.0"
MODEL_CONFIG_ID="MODEL-CATALOG-V1"
MODEL_SETTINGS_ID="MODEL-SETTINGS-V1"
RAG_CONFIG_ID="RAG-LEXICAL-V1"
ORCH_CONFIG_ID="ORCH-ADAPTIVE-AUTO-V1"
SINGLE_CONFIG_ID="SINGLE-DIRECT-V1"
FIXED_CONFIG_ID="FIXED-TOPOLOGY-V1"
STATIC_CONFIG_ID="STATIC-PRESETS-V1"
PRICE_CONFIG_ID="PRICE-TABLE-V1"

# Fixed is based on the existing baseline path (Planner + three Worker slots,
# observational Verifier, Synthesizer). Only task text supplied to each slot
# may vary; IDs, count, dependency policy, and role topology do not.
FIXED_TOPOLOGY={
    "config_id":FIXED_CONFIG_ID,
    "config_version":CONFIG_VERSION,
    "role_sequence":["Planner","Worker:S1","Worker:S2","Worker:S3",
                      "Runtime Verifier","Synthesizer"],
    "topology_signature":"Planner>S1|S2|S3>RuntimeVerifier>Synthesizer",
    "worker_count":3,
    "planner":True,
    "verifier":True,
    "synthesizer":True,
    "concurrency":"S1/S2/S3 independent ready-set batch",
    "dependency_policy":"fixed independent worker slots",
    "runtime_escalation":False,
}

# Static performs one initial structural analysis and chooses exactly one of
# these explicit presets. The preset's topology is frozen for the rest of a
# run. Verifier is observational (like Fixed): NEEDS_WORK is recorded but
# cannot add workers or switch the preset.
STATIC_PRESETS={
    "DIRECT":{
        "preset_id":"STATIC-DIRECT-V1","preset_version":CONFIG_VERSION,
        "mode":"DIRECT","role_sequence":["Direct Solver","Runtime Verifier"],
        "topology_signature":"DirectSolver>RuntimeVerifier",
        "worker_count":0,"planner":False,"verifier":True,"synthesizer":False,
        "concurrency":"none","dependency_policy":"none","runtime_escalation":False,
    },
    "PARALLEL":{
        "preset_id":"STATIC-PARALLEL-V1","preset_version":CONFIG_VERSION,
        "mode":"PARALLEL","role_sequence":["Worker:S1","Worker:S2","Worker:S3",
                                               "Synthesizer","Runtime Verifier"],
        "topology_signature":"S1|S2|S3>Synthesizer>RuntimeVerifier",
        "worker_count":3,"planner":False,"verifier":True,"synthesizer":True,
        "concurrency":"S1/S2/S3 concurrent","dependency_policy":"fixed independent worker slots",
        "runtime_escalation":False,
    },
    "PLANNED":{
        "preset_id":"STATIC-PLANNED-V1","preset_version":CONFIG_VERSION,
        "mode":"PLANNED","role_sequence":["Planner","Worker:S1","Worker:S2","Worker:S3",
                                               "Synthesizer","Runtime Verifier"],
        "topology_signature":"Planner>S1|S2|S3>Synthesizer>RuntimeVerifier",
        "worker_count":3,"planner":True,"verifier":True,"synthesizer":True,
        "concurrency":"S1/S2/S3 concurrent","dependency_policy":"fixed independent worker slots",
        "runtime_escalation":False,
    },
}

def _budget_identity(budget):
    return {
        "max_logical_calls":budget.max_logical_calls,
        "max_physical_requests":budget.max_physical_requests,
        "max_workers":budget.max_workers,
        "max_escalations":budget.max_escalations,
        "max_retries_per_call":budget.max_retries_per_call,
        "call_timeout_seconds":budget.call_timeout_seconds,
        "retry_base_seconds":budget.retry_base_seconds,
        "retry_max_seconds":budget.retry_max_seconds,
    }

def strategy_config_identity(strategy, budget, *, selected_preset=None,
                             retrieval_meta=None):
    """Return safe, versioned configuration identity for persisted evidence."""
    if strategy=="single": strategy_id=SINGLE_CONFIG_ID
    elif strategy=="fixed": strategy_id=FIXED_CONFIG_ID
    elif strategy=="static": strategy_id=STATIC_CONFIG_ID
    else: strategy_id=ORCH_CONFIG_ID
    identity={
        "strategy_config_id":strategy_id,
        "strategy_config_version":CONFIG_VERSION,
        "model_config_id":MODEL_CONFIG_ID,
        "model_settings_id":MODEL_SETTINGS_ID,
        "rag_config_id":(retrieval_meta or {}).get("retrieval_config_id",RAG_CONFIG_ID),
        "orchestrator_config_id":ORCH_CONFIG_ID,
        "price_config_id":PRICE_CONFIG_ID,
        "prompt_versions":dict(PROMPT_VERSIONS),
        "budget":_budget_identity(budget),
    }
    if strategy=="fixed":
        identity["fixed_config_id"]=FIXED_CONFIG_ID
        identity["fixed_config_version"]=CONFIG_VERSION
        identity["fixed_topology"]={
            **FIXED_TOPOLOGY,
            "retry":{"max_retries_per_call":budget.max_retries_per_call},
            "timeout_seconds":budget.call_timeout_seconds,
            "budget":_budget_identity(budget),
        }
    if strategy=="static":
        identity["static_config_id"]=STATIC_CONFIG_ID
        identity["static_config_version"]=CONFIG_VERSION
        if selected_preset:
            identity["selected_preset"]=selected_preset.get("preset_id")
            identity["selected_preset_version"]=selected_preset.get("preset_version")
            identity["static_preset"]={
                **selected_preset,
                "retry":{"max_retries_per_call":budget.max_retries_per_call},
                "timeout_seconds":budget.call_timeout_seconds,
                "budget":_budget_identity(budget),
            }
    return identity

class Orchestrator:
    def __init__(self,provider,emit,*,budget,request_gate=None):
        self.provider=provider; self.emit=emit; self.budget=budget
        # Optional experiment-level pacing gate.  It is shared across all
        # roles/strategies in a Pilot executor; normal chat remains unchanged.
        self.request_gate=request_gate

    def _set_config_identity(self,state,*,selected_preset=None):
        state.config_identity=strategy_config_identity(
            state.strategy,self.budget,selected_preset=selected_preset,
            retrieval_meta=state.retrieval_meta,
        )

    async def _event(self,state,kind,title,detail="",meta=None):
        e=state.event(kind,title,detail,meta); await self.emit({"type":"trace","event":e})

    def _retry_delay(self,exc,attempt):
        base=max(0.1,float(getattr(self.budget,"retry_base_seconds",os.getenv("RETRY_BASE_SECONDS","1"))))
        maximum=max(base,float(getattr(self.budget,"retry_max_seconds",os.getenv("RETRY_MAX_SECONDS","60"))))
        response=getattr(exc,"response",None)
        status=getattr(response,"status_code",None)
        hinted=0.0
        if response is not None:
            retry_after=response.headers.get("retry-after")
            if retry_after:
                try: hinted=float(retry_after)
                except ValueError: pass
            try:
                body=json.dumps(response.json())
                delays=[float(value) for value in re.findall(r'"retryDelay"\s*:\s*"([0-9.]+)s"',body)]
                if delays: hinted=max(hinted,max(delays))
            except Exception: pass
        fallback=15.0 if status==429 else 2.0 if status in {500,502,503,504} else base
        return min(maximum,max(hinted,fallback,base*(2**attempt)))

    @staticmethod
    def _safe_preview(value,limit=320):
        return redact_secrets(str(value or "")).replace("\r"," ").replace("\n"," ").strip()[:limit]

    async def _call(self,state,role,system,user,prompt_version,transform=None,execution_meta=None):
        self.budget.start_logical()
        state.agent_executions += 1
        execution_id=f"AE-{state.agent_executions:03d}"
        logical_call=self.budget.logical_calls
        execution_meta=execution_meta or {}
        assigned_goal=self._safe_preview(execution_meta.get("assigned_goal") or f"Execute bounded {role} role")
        dependencies=[self._safe_preview(item,80) for item in (execution_meta.get("dependencies") or [])]
        started=time.perf_counter(); start_ms=round((started-state.started_at)*1000)
        base_meta={"execution_id":execution_id,"logical_call":logical_call,"role":role,
                   "agent_type":execution_meta.get("agent_type") or role.split(" · ",1)[0],
                   "assigned_goal":assigned_goal,"dependencies":dependencies,
                   "prompt_version":prompt_version,"provider":self.provider.name,
                   "model":self.provider.model,"start_ms":start_ms}
        for key in ("subtask_id","targeted_repair","escalation_issue"):
            if key in execution_meta and execution_meta[key] is not None:
                base_meta[key]=self._safe_preview(execution_meta[key],160) if key in {"subtask_id","escalation_issue"} else bool(execution_meta[key])
        await self._event(state,"agent_start",role,f"Logical call #{logical_call}",{**base_meta,"status":"running"})
        last=None
        for attempt in range(self.budget.max_retries_per_call+1):
            self.budget.record_request()
            release_gate = None
            if self.request_gate is not None:
                release_gate = await self.request_gate()
            await self._event(state,"provider_request",f"{role} · provider request",
                              f"attempt {attempt+1}",{**base_meta,"attempt":attempt+1,"physical_request":self.budget.physical_requests})
            provider_succeeded = False
            try:
                result=await asyncio.wait_for(
                    self.provider.generate(system=system,user=user),
                    timeout=self.budget.call_timeout_seconds
                )
                provider_succeeded = True
                state.record_usage(result)
                if self.request_gate is not None and hasattr(self.request_gate, "record_tokens"):
                    usage = result.usage
                    measured = None
                    if usage is not None and result.usage_metadata_available is not False:
                        measured = int(getattr(usage, "total_tokens", 0) or 0)
                    if not measured:
                        measured = max(1, (len(system) + len(user)) // 4)
                    self.request_gate.record_tokens(measured)
                value=transform(result.text) if transform else result.text
                usage=result.usage
                if usage is None:
                    usage=Usage()
                usage_available=result.usage_metadata_available
                if usage_available is None:
                    usage_available=bool(usage.input_tokens or usage.output_tokens or usage.total_tokens)
                input_tokens=usage.input_tokens if usage_available else None
                output_tokens=usage.output_tokens if usage_available else None
                total_tokens=usage.total_tokens if usage_available else None
                cached_input_tokens=usage.cached_input_tokens if usage_available else None
                reasoning_tokens=usage.reasoning_tokens if usage_available else None
                ended=time.perf_counter(); end_ms=round((ended-state.started_at)*1000); ms=round((ended-started)*1000)
                await self._event(state,"agent_end",role,f"Completed in {ms} ms",
                                  {**base_meta,"status":"completed","end_ms":end_ms,"duration_ms":ms,
                                   "provider":self.provider.name,"model":result.model or self.provider.model,
                                   "usage_metadata_available":bool(usage_available),
                                   "input_tokens":input_tokens,"output_tokens":output_tokens,
                                   "total_tokens":total_tokens,"tokens":total_tokens,
                                   "cached_input_tokens":cached_input_tokens,
                                   "reasoning_tokens":reasoning_tokens,
                                   "request_id":result.request_id,"output_preview":self._safe_preview(result.text)})
                await self.emit({"type":"metrics","metrics":self.metrics(state)})
                return value
            except Exception as exc:
                last=exc
                if provider_succeeded:
                    incident = safe_runtime_incident(
                        category="STRATEGY_TERMINAL_FAILURE",
                        safe_message="Provider output could not be validated for this bounded role.",
                        provider=self.provider.name,
                        model=self.provider.model,
                        origin="runtime",
                        attempt=attempt + 1,
                        retry=attempt,
                    )
                else:
                    incident = safe_provider_incident(
                        exc,
                        provider=self.provider.name,
                        model=self.provider.model,
                        attempt=attempt + 1,
                        retry=attempt,
                    )
                state.incident_records.append(incident)
                state.outcome_category = incident.get("category")
                gate_owner = getattr(self.request_gate, "__self__", None)
                if gate_owner is None and hasattr(self.request_gate, "note_retry_after"):
                    gate_owner = self.request_gate
                if gate_owner is not None and hasattr(gate_owner, "note_retry_after"):
                    gate_owner.note_retry_after(incident.get("retry_after_seconds"))
                safe_error=incident.get("safe_message") or "Bounded role execution failed."
                if attempt<self.budget.max_retries_per_call and self.budget.can_request():
                    delay=self._retry_delay(exc,attempt)
                    await self._event(state,"retry",f"{role} · retry",safe_error,
                                      {**base_meta,"next_attempt":attempt+2,"delay_seconds":round(delay,2),
                                       "incident":incident})
                    await asyncio.sleep(delay)
                else:
                    ended=time.perf_counter(); end_ms=round((ended-state.started_at)*1000)
                    await self._event(state,"agent_error",role,safe_error,
                                      {**base_meta,"status":"failed","end_ms":end_ms,
                                       "duration_ms":round((ended-started)*1000),"provider":self.provider.name,
                                       "model":self.provider.model,"error":self._safe_preview(safe_error),
                                       "incident":incident})
                    raise
            finally:
                if release_gate is not None:
                    release_gate()
        raise last

    def prompt(self,state,extra=""):
        return f"CURRENT USER TASK:\n{state.task}\n\nRECENT CONVERSATION CONTEXT:\n{state.chat_history or '(none)'}\n\nFROZEN REFERENCE CONTEXT:\n{state.context}\n\n{extra}"

    async def analyze(self,state):
        def validate(text):
            data=parse_json(text)
            if not isinstance(data.get("aspects"),list): raise ValueError("Analyzer JSON must include aspects[]")
            if not isinstance(data.get("dependencies"),list): raise ValueError("Analyzer JSON must include dependencies[]")
            if not isinstance(data.get("parallelizable_groups"),list): raise ValueError("Analyzer JSON must include parallelizable_groups[]")
            if data.get("verification_demand") not in {"low","medium","high"}: raise ValueError("Invalid verification_demand")
            if not isinstance(data.get("verification_reasons"),list): raise ValueError("Analyzer JSON must include verification_reasons[]")
            if not isinstance(data.get("rationale"),str): raise ValueError("Analyzer JSON must include rationale")
            return data
        a=await self._call(state,"Analyzer",ANALYZER_SYS,self.prompt(state),PROMPT_VERSIONS["analyzer"],validate,
                            {"agent_type":"Analyzer","assigned_goal":"Extract aspects, dependencies, parallelizability, verification demand and rationale","dependencies":[]})
        aspects=a.get("aspects") or []
        deps=a.get("dependencies") or []
        verify=a.get("verification_demand","low")
        await self._event(state,"analysis","Structural signals",
            f"{len(aspects)} aspect(s) · {len(deps)} dependency edge(s) · verification={verify}",a)
        return a

    def choose_mode(self,a):
        aspects=a.get("aspects") or []
        deps=a.get("dependencies") or []
        groups=a.get("parallelizable_groups") or []
        verify=a.get("verification_demand","low")
        if deps or verify=="high":
            return "PLANNED","dependency and/or high verification demand"
        if len(aspects)>1 and any(len(g)>1 for g in groups):
            return "PARALLEL","multiple relatively independent aspects"
        return "DIRECT","single-focus or no useful decomposition"

    def choose_static_preset(self,a):
        """Select one Static preset exactly once from initial structural signals.

        This intentionally duplicates the small rule table instead of calling
        Adaptive's runtime route method: after this decision Static has no
        controller hook that can change the selected preset.
        """
        aspects=a.get("aspects") or []
        deps=a.get("dependencies") or []
        groups=a.get("parallelizable_groups") or []
        verify=a.get("verification_demand","low")
        if deps or verify=="high":
            return "PLANNED","dependency and/or high verification demand"
        if len(aspects)>1 and any(len(g)>1 for g in groups):
            return "PARALLEL","multiple relatively independent aspects"
        return "DIRECT","single-focus or no useful decomposition"

    def select_agents(self,a,mode):
        aspects=a.get("aspects") or []
        if mode=="DIRECT":
            selected={"direct_solver":1,"planner":0,"workers":0,"verifier":1,"synthesizer":0}
        elif mode=="PARALLEL":
            selected={"direct_solver":0,"planner":0,"workers":min(max(2,len(aspects)),self.budget.max_workers),"verifier":1,"synthesizer":1}
        else:
            selected={"direct_solver":0,"planner":1,"workers":min(max(1,len(aspects)),self.budget.max_workers),"verifier":1,"synthesizer":1}
        return selected

    def parallel_subtasks(self,a):
        aspects=a.get("aspects") or []
        items=[]
        for i,x in enumerate(aspects[:self.budget.max_workers],1):
            if isinstance(x,dict):
                goal=x.get("goal") or x.get("name") or f"Aspect {i}"
            else: goal=str(x)
            items.append({"id":f"S{i}","goal":goal,"depends_on":[]})
        if not items:
            items=[{"id":"S1","goal":"Solve the requested aspect","depends_on":[]}]
        return items

    @staticmethod
    def fixed_worker_slots(proposed=None,count=3):
        """Map optional Planner goals onto the immutable S1..S3 topology."""
        proposed=proposed if isinstance(proposed,list) else []
        goals=[]
        for item in proposed:
            if isinstance(item,dict):
                goals.append(str(item.get("goal") or "Complete the assigned evidence pass"))
            elif item is not None:
                goals.append(str(item))
        fallback="Complete the assigned evidence pass for the original task"
        return [
            {"id":f"S{index}","goal":goals[index-1] if index<=len(goals) else fallback,
             "depends_on":[]}
            for index in range(1,count+1)
        ]

    def static_subtasks(self,a,preset,proposed=None):
        """Build the selected Static preset's fixed worker slots."""
        count=int(preset.get("worker_count",0))
        if count<=0: return []
        if proposed is None:
            proposed=self.parallel_subtasks(a)
        return self.fixed_worker_slots(proposed,count=count)

    async def plan(self,state,*,emit_validation=True,validate_output=True):
        def validate(text):
            data=parse_json(text); subtasks=data.get("subtasks")
            if not isinstance(subtasks,list) or not subtasks: raise ValueError("Planner JSON must include non-empty subtasks[]")
            for subtask in subtasks:
                if not isinstance(subtask,dict) or not subtask.get("id") or not subtask.get("goal") or not isinstance(subtask.get("depends_on",[]),list):
                    raise ValueError("Each subtask requires id, goal and depends_on[]")
            if validate_output:
                validate_plan(subtasks)
            return subtasks
        subtasks=await self._call(state,"Planner",PLANNER_SYS,self.prompt(state),PROMPT_VERSIONS["planner"],validate,
                                  {"agent_type":"Planner","assigned_goal":"Build and validate the smallest useful dependency DAG","dependencies":[]})
        if emit_validation:
            await self._event(state,"plan","DAG validated",f"{len(subtasks)} node(s) · Kahn cycle check passed",{"subtasks":subtasks})
        else:
            await self._event(state,"plan","Planner proposal",
                              f"{len(subtasks)} task goal(s) mapped into frozen slots",
                              {"subtasks":subtasks,"topology_frozen":True})
        return subtasks

    async def worker(self,state,subtask,*,escalation_issue=None):
        return await self._call(state,f"Worker · {subtask['id']}",WORKER_SYS,
             self.prompt(state,f"ASSIGNED SUBTASK:\n{subtask['id']}: {subtask['goal']}"),
             PROMPT_VERSIONS["worker"],execution_meta={"agent_type":"Worker","assigned_goal":subtask["goal"],
             "dependencies":subtask.get("depends_on",[]),"subtask_id":subtask["id"],
             "targeted_repair":subtask["id"].startswith("T"),"escalation_issue":escalation_issue})

    async def execute_dag(self,state,subtasks):
        validate_plan(subtasks)
        done=set(); outputs={}
        while len(done)<len(subtasks):
            ready=ready_nodes(subtasks,done)
            if not ready: raise RuntimeError("STOP_INVALID_DAG_STATE")
            batch=ready[:self.budget.max_workers]
            await self._event(state,"scheduler","Ready-set batch",
                " + ".join(s["id"] for s in batch),
                {"algorithm":"Kahn-style ready set","parallel":len(batch)>1,"nodes":[s["id"] for s in batch]})
            results=await asyncio.gather(*(self.worker(state,s) for s in batch))
            for s,r in zip(batch,results): outputs[s["id"]]=r; done.add(s["id"])
        return outputs

    async def synthesize(self,state,outputs):
        return await self._call(state,"Synthesizer",SYNTH_SYS,
            self.prompt(state,"WORKER RESULTS:\n"+json.dumps(outputs,ensure_ascii=False)),
            PROMPT_VERSIONS["synth"],execution_meta={"agent_type":"Synthesizer",
            "assigned_goal":"Combine bounded worker results into one candidate answer",
            "dependencies":list(outputs.keys()) if isinstance(outputs,dict) else []})

    async def verify(self,state,candidate,targeted_repair=False):
        marker="\n[targeted_fix_done]" if targeted_repair else ""
        def validate(text):
            data=parse_json(text)
            status=str(data.get("status","")).upper()
            if status not in {"PASS","NEEDS_WORK","FAIL"}: raise ValueError("Invalid verifier status")
            issues=data.get("issues",[])
            if not isinstance(issues,list): raise ValueError("Verifier issues must be a list")
            data["status"]=status; data["issues"]=issues
            return data
        v=await self._call(state,"Runtime Verifier",VERIFIER_SYS,
            self.prompt(state,f"CANDIDATE ANSWER:\n{candidate}{marker}"),
            PROMPT_VERSIONS["verifier"],validate,execution_meta={"agent_type":"Verifier",
            "assigned_goal":"Check candidate sufficiency and report PASS, NEEDS_WORK or FAIL",
            "dependencies":["candidate"],"targeted_repair":targeted_repair})
        await self._event(state,"verification","Verifier · "+v.get("status","UNKNOWN"),
                          v.get("rationale",""),{**v,"targeted_repair":targeted_repair})
        return v

    async def direct(self,state):
        return await self._call(state,"Direct Solver",SOLVER_SYS,self.prompt(state),PROMPT_VERSIONS["solver"],
                                execution_meta={"agent_type":"Direct Solver","assigned_goal":"Answer the original task from frozen context","dependencies":[]})

    async def run_adaptive(self,state):
        a=await self.analyze(state)
        mode,why=self.choose_mode(a)
        agents=self.select_agents(a,mode)
        await self._event(state,"decision","AUTO route selected",mode,{"mode":mode,"why":why,"selected_agents":agents})
        await self._event(state,"agent_selection","Agent selection",
                          ", ".join(f"{k}={v}" for k,v in agents.items() if v),agents)

        if mode=="DIRECT":
            candidate=await self.direct(state)
        elif mode=="PARALLEL":
            subtasks=self.parallel_subtasks(a)
            await self._event(state,"plan","Parallel plan from structural aspects",f"{len(subtasks)} independent node(s)",{"subtasks":subtasks})
            candidate=await self.synthesize(state,await self.execute_dag(state,subtasks))
        else:
            candidate=await self.synthesize(state,await self.execute_dag(state,await self.plan(state)))
        # Keep the latest usable draft on the state before the quality gate.
        # If a later worker/verifier call fails, the final event can still show
        # the draft instead of turning a useful response into an empty answer.
        state.answer=candidate

        # A verifier is a quality gate, not the source of the answer.  Providers
        # can be rate-limited after the expensive solve/synthesis calls (this is
        # common with Flash-Lite).  Keep the usable candidate and report a
        # degraded run instead of replacing it with an empty failed response.
        try:
            v=await self.verify(state,candidate)
        except Exception as exc:
            incident = state.incident_records[-1] if state.incident_records else safe_runtime_incident(
                category="EXPERIMENT_INFRASTRUCTURE_ERROR",
                safe_message="Runtime Verifier was unavailable.",
                provider=self.provider.name,
                model=self.provider.model,
                origin="verifier",
            )
            if not state.incident_records:
                state.incident_records.append(incident)
            safe_error=incident.get("safe_message") or "Runtime Verifier was unavailable."
            state.outcome_category = incident.get("category") or "EXPERIMENT_INFRASTRUCTURE_ERROR"
            state.status="degraded"
            state.stop_reason="STOP_VERIFICATION_UNAVAILABLE"
            await self._event(state,"verification_unavailable","Runtime Verifier unavailable",
                              safe_error,{"candidate_preserved":True,"incident":incident})
            return candidate
        if v.get("status")=="PASS":
            state.stop_reason="STOP_SUFFICIENT"
            await self._event(state,"stop","Early stop · sufficient","Runtime Verifier passed. No extra Agent call.")
            return candidate

        if v.get("status")=="NEEDS_WORK" and self.budget.allow_escalation():
            issues=v.get("issues") or []
            max_fixes=min(
                self.budget.max_workers,
                self.budget.remaining_logical_calls-2,
                self.budget.remaining_physical_requests-2,
            )
            issue_targets=[(i.get("target") or i.get("description") or "Resolve verifier issue") for i in issues[:max_fixes]]
            issue_targets=issue_targets or ["Resolve verifier issue"]
            self.budget.escalations += 1
            repair_subtasks=[{"id":f"T{idx}","goal":target,"depends_on":[]} for idx,target in enumerate(issue_targets,1)]
            await self._event(state,"decision","Targeted escalation",
                              f"{len(repair_subtasks)} targeted issue(s), round {self.budget.escalations}",
                              {"issues":issues,"subtasks":repair_subtasks,"round":self.budget.escalations})
            repair_issues=issues[:len(repair_subtasks)] if issues else [{}]
            repair_results=await asyncio.gather(*(self.worker(
                state,subtask,escalation_issue=(issue.get("target") or issue.get("description") or "Resolve verifier issue")
                if isinstance(issue,dict) else str(issue)) for subtask,issue in zip(repair_subtasks,repair_issues)))
            fixes={subtask["id"]:result for subtask,result in zip(repair_subtasks,repair_results)}
            candidate=await self.synthesize(state,{"previous_candidate":candidate,"targeted_fixes":fixes})
            state.answer=candidate
            try:
                v2=await self.verify(state,candidate,targeted_repair=True)
            except Exception as exc:
                incident = state.incident_records[-1] if state.incident_records else safe_runtime_incident(
                    category="EXPERIMENT_INFRASTRUCTURE_ERROR",
                    safe_message="Runtime Verifier was unavailable after targeted repair.",
                    provider=self.provider.name,
                    model=self.provider.model,
                    origin="verifier",
                )
                if not state.incident_records:
                    state.incident_records.append(incident)
                safe_error=incident.get("safe_message") or "Runtime Verifier was unavailable."
                state.outcome_category = incident.get("category") or "EXPERIMENT_INFRASTRUCTURE_ERROR"
                state.status="degraded"
                state.stop_reason="STOP_VERIFICATION_UNAVAILABLE"
                await self._event(state,"verification_unavailable","Runtime Verifier unavailable",
                                  safe_error,{"candidate_preserved":True,"after_escalation":True,"incident":incident})
                return candidate
            if v2.get("status")=="PASS":
                state.stop_reason="STOP_SUFFICIENT"
                await self._event(state,"stop","Early stop after escalation","Targeted repair passed.")
                return candidate

        state.stop_reason="STOP_BUDGET_OR_VERIFICATION"
        await self._event(state,"stop",state.stop_reason,"No further adaptive work allowed by policy/budget.")
        return candidate

    async def run_single(self,state):
        return await self.direct(state)

    async def run_fixed(self,state):
        # Planner remains part of the existing Fixed baseline, but its output
        # is task text only. IDs, count, dependency policy, concurrency, and
        # role presence come from FIXED_TOPOLOGY and cannot vary by task.
        await self._event(state,"decision","Fixed topology frozen",
                          f"{FIXED_CONFIG_ID} · {FIXED_TOPOLOGY['worker_count']} Worker slots",
                          {**FIXED_TOPOLOGY,"strategy_config_id":FIXED_CONFIG_ID,
                           "strategy_config_version":CONFIG_VERSION,
                           "config_identity":state.config_identity})
        proposed=await self.plan(state,emit_validation=False,validate_output=False)
        subtasks=self.fixed_worker_slots(proposed,count=FIXED_TOPOLOGY["worker_count"])
        await self._event(state,"plan","Fixed worker slots",
                          " + ".join(item["id"] for item in subtasks),
                          {"config_id":FIXED_CONFIG_ID,"config_version":CONFIG_VERSION,
                           "subtasks":subtasks,"topology_signature":FIXED_TOPOLOGY["topology_signature"]})
        outputs=await self.execute_dag(state,subtasks)
        draft="\n\n".join(outputs.values())
        _=await self.verify(state,draft)  # observational only
        return await self.synthesize(state,outputs)

    async def run_static(self,state):
        a=await self.analyze(state)
        mode,why=self.choose_static_preset(a)
        preset=STATIC_PRESETS[mode]
        self._set_config_identity(state,selected_preset=preset)
        await self._event(state,"decision","Static route frozen",mode,
                          {"mode":mode,"why":why,"preset_id":preset["preset_id"],
                           "preset_version":preset["preset_version"],
                           "preset":preset,"runtime_preset_change_allowed":False,
                           "config_identity":state.config_identity})
        if mode=="DIRECT":
            candidate=await self.direct(state)
        elif mode=="PARALLEL":
            slots=self.static_subtasks(a,preset)
            await self._event(state,"plan","Static preset worker slots",
                              " + ".join(item["id"] for item in slots),
                              {"preset_id":preset["preset_id"],"preset_version":preset["preset_version"],
                               "subtasks":slots,"topology_frozen":True})
            candidate=await self.synthesize(state,await self.execute_dag(state,slots))
        else:
            # Planner may tailor goal text, but fixed slot IDs and independent
            # dependency policy prevent it from changing this selected preset.
            slots=self.static_subtasks(a,preset,await self.plan(
                state,emit_validation=False,validate_output=False))
            await self._event(state,"plan","Static preset worker slots",
                              " + ".join(item["id"] for item in slots),
                              {"preset_id":preset["preset_id"],"preset_version":preset["preset_version"],
                               "subtasks":slots,"topology_frozen":True})
            candidate=await self.synthesize(state,await self.execute_dag(state,slots))
        if preset.get("verifier"):
            verdict=await self.verify(state,candidate)
            await self._event(state,"verification","Static verifier observed",
                              verdict.get("status","UNKNOWN"),
                              {**verdict,"preset_id":preset["preset_id"],
                               "adaptive_escalation_allowed":False})
        return candidate

    async def run(self,state):
        self._set_config_identity(state)
        await self._event(state,"rag","Frozen Context Snapshot",
            f"{state.retrieval_meta.get('chunks_selected',0)}/{state.retrieval_meta.get('chunks_total',0)} chunk(s) selected",
            state.retrieval_meta)
        await self._event(state,"run","Run started",f"{state.strategy} · {state.provider} · {state.model}")
        try:
            if state.strategy=="adaptive": answer=await self.run_adaptive(state)
            elif state.strategy=="single": answer=await self.run_single(state)
            elif state.strategy=="fixed": answer=await self.run_fixed(state)
            elif state.strategy=="static": answer=await self.run_static(state)
            else: raise ValueError("Unknown strategy")
            state.answer=answer
            if state.status == "running":
                state.status="completed"
            if not state.stop_reason: state.stop_reason="COMPLETED"
        except RuntimeError as exc:
            latest_incident = state.incident_records[-1] if state.incident_records else None
            if latest_incident and latest_incident.get("origin") == "provider":
                state.status="stopped"
                state.stop_reason="STOP_PROVIDER_INCIDENT"
                state.error=latest_incident.get("safe_message") or "Provider execution failed."
                state.outcome_category=latest_incident.get("category")
            else:
                state.status="stopped"; state.stop_reason=str(exc)
                if latest_incident:
                    state.error = latest_incident.get("safe_message") or "Bounded run stopped."
                    state.outcome_category = latest_incident.get("category") or "STRATEGY_TERMINAL_FAILURE"
            await self._event(state,"stop",state.stop_reason,"Run stopped by runtime policy.")
        except Exception as exc:
            state.status="failed"; state.stop_reason="STOP_FAILURE"
            if state.incident_records:
                state.error = state.incident_records[-1].get("safe_message") or "Bounded run failed."
                state.outcome_category = state.incident_records[-1].get("category")
            else:
                state.error="Bounded run failed."
                state.outcome_category = "STRATEGY_TERMINAL_FAILURE"
            await self._event(state,"error","Run failed",state.error)
        state.finished_at=time.perf_counter()
        if state.status == "completed" and state.answer:
            state.outcome_category="SUCCESS"
        elif not state.outcome_category:
            state.outcome_category = (
                "EXPERIMENT_INFRASTRUCTURE_ERROR"
                if state.stop_reason == "STOP_VERIFICATION_UNAVAILABLE"
                else "STRATEGY_TERMINAL_FAILURE"
            )
        await self.emit({"type":"final","answer":state.answer,"status":state.status,
                         "stop_reason":state.stop_reason,"metrics":self.metrics(state),
                         "run_id":state.run_id,"provider":state.provider,"model":state.model,
                         "error":state.error or None})
        return state

    def metrics(self,state):
        usage_available=state.usage_metadata_available is True
        inp=state.usage.input_tokens if usage_available else None
        out=state.usage.output_tokens if usage_available else None
        cached=state.usage.cached_input_tokens if usage_available else None
        reasoning=state.usage.reasoning_tokens if usage_available else None
        rate=PRICE_PER_MTOK.get(state.model)
        cached_rate=CACHED_INPUT_PRICE_PER_MTOK.get(state.model)
        if rate and inp is not None and out is not None:
            if cached_rate is not None and cached is not None:
                cached_tokens=min(max(int(cached),0),int(inp))
                uncached_tokens=max(int(inp)-cached_tokens,0)
                cost=((uncached_tokens/1_000_000)*rate[0]
                      +(cached_tokens/1_000_000)*cached_rate
                      +(out/1_000_000)*rate[1])
            else:
                # Without a cache breakdown, do not invent a discount. The
                # published uncached input rate is the conservative fallback.
                cost=((inp/1_000_000)*rate[0]+(out/1_000_000)*rate[1])
        else:
            cost=None
        return {
            "agent_executions":state.agent_executions,
            "logical_calls":self.budget.logical_calls,
            "physical_requests":self.budget.physical_requests,
            "input_tokens":inp,"output_tokens":out,"total_tokens":(inp+out) if inp is not None and out is not None else None,
            "cached_input_tokens":cached,
            "reasoning_tokens":reasoning,
            "usage_metadata_available":usage_available,
            "e2e_ms":round(((state.finished_at or time.perf_counter())-state.started_at)*1000),
            "e2e_boundary_version":"E2E-MEASURE-V2",
            "context_prep_ms":state.retrieval_meta.get("context_prep_ms"),
            "retries":sum(1 for event in state.events if event.get("kind") == "retry"),
            "escalations":self.budget.escalations,
            "calculated_cost_usd":round(cost,8) if cost is not None else None,
            "pricing_model":state.model if rate else None,
        }
