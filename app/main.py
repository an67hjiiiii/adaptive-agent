from __future__ import annotations
import asyncio,hashlib,json,os,re,time,uuid
from copy import deepcopy
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from dotenv import load_dotenv
load_dotenv()

from app.providers.factory import get_provider
from app.core.types import RunState,Budget
from app.core.orchestrator import (
    MODEL_CONFIG_ID,
    MODEL_SETTINGS_ID,
    PRICE_CONFIG_ID,
    Orchestrator,
    strategy_config_identity,
)
from app.core.rag import frozen_snapshot
from app.core.provider_diagnostics import (
    SAFE_MESSAGES,
    classify_provider_error,
    diagnostic_for_category,
    run_provider_diagnostic,
)
from app.core.incidents import (
    INCIDENT_TAXONOMY_VERSION,
    run_category_for_provider,
    safe_provider_incident,
    safe_runtime_incident,
)
from app.core.security import redact_secrets

BASE=Path(__file__).resolve().parent
RUNS=BASE.parent/"runs"; RUNS.mkdir(exist_ok=True)
CONVERSATIONS=RUNS/"conversations"; CONVERSATIONS.mkdir(exist_ok=True)
PROVIDER_STATUS=RUNS/"provider_status.json"
APP_VERSION="0.6.3"
app=FastAPI(title="Adaptive Agent Lab",version=APP_VERSION)
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

@app.middleware("http")
async def local_fresh_assets(request:Request,call_next):
    """Never let the local demo keep an obsolete UI/API contract in an open tab."""
    response=await call_next(request)
    path=request.url.path
    if path=="/" or path.startswith("/static/") or path in {"/api/health","/api/config"}:
        response.headers["Cache-Control"]="no-store, max-age=0"
        response.headers["Pragma"]="no-cache"
    return response

class ChatRequest(BaseModel):
    message:str=Field(min_length=1,max_length=12000)
    context:str=Field(default="",max_length=100000)
    provider:str=Field(default="fake",pattern="^(fake|openai|gemini|groq|openrouter)$")
    model:str|None=Field(default=None,max_length=80)
    conversation_id:str|None=Field(default=None,pattern="^chat_[A-Za-z0-9_-]+$")
    history:list[dict]=Field(default_factory=list)

class CompareRequest(ChatRequest): pass
class ProviderTestRequest(BaseModel):
    provider:str=Field(pattern="^(fake|openai|gemini|groq|openrouter)$")
    model:str|None=Field(default=None,max_length=80)

def model_catalog():
    defaults={
      "fake":"fake-research-v2",
      "gemini":os.getenv("GEMINI_MODEL","gemini-3.7-flash"),
      "groq":os.getenv("GROQ_MODEL","openai/gpt-oss-120b"),
      "openrouter":os.getenv("OPENROUTER_MODEL","openrouter/free"),
      "openai":os.getenv("OPENAI_MODEL","gpt-5.6-luna"),
    }
    options={
      "fake":[{"id":"fake-research-v2","label":"Fake Research v2","tier":"offline"}],
      "gemini":[
        {"id":"gemini-3.7-flash","label":"Gemini 3.7 Flash","tier":"recommended"},
        {"id":"gemini-3.6-flash","label":"Gemini 3.6 Flash","tier":"balanced"},
        {"id":"gemini-3.5-flash-lite","label":"Gemini 3.5 Flash-Lite","tier":"economy"},
      ],
      "groq":[
        {"id":"openai/gpt-oss-120b","label":"GPT-OSS 120B · Groq","tier":"fast"},
        {"id":"openai/gpt-oss-20b","label":"GPT-OSS 20B · Groq","tier":"faster"},
        {"id":"llama-3.3-70b-versatile","label":"Llama 3.3 70B · Groq","tier":"general"},
      ],
      "openrouter":[
        {"id":"openrouter/free","label":"OpenRouter Free Router","tier":"dev-only"},
      ],
      "openai":[
        {"id":"gpt-5.6-luna","label":"GPT-5.6 Luna","tier":"economy"},
        {"id":"gpt-5.6-terra","label":"GPT-5.6 Terra","tier":"balanced"},
        {"id":"gpt-5.6-sol","label":"GPT-5.6 Sol","tier":"quality"},
      ],
    }
    for provider,current in defaults.items():
        if current not in {item["id"] for item in options[provider]}:
            options[provider].insert(0,{"id":current,"label":current,"tier":"custom"})
    return defaults,options

def validated_model(provider,requested=None):
    defaults,options=model_catalog()
    model=requested or defaults[provider]
    if model not in {item["id"] for item in options[provider]}:
        raise HTTPException(status_code=400,detail="Unsupported model selection")
    return model

def make_budget(settings=None):
    settings=settings or {}
    return Budget(
      max_logical_calls=int(settings.get("max_logical_calls",os.getenv("MAX_LOGICAL_CALLS","12"))),
      max_physical_requests=int(settings.get("max_physical_requests",os.getenv("MAX_PHYSICAL_REQUESTS","18"))),
      max_workers=int(settings.get("max_workers",os.getenv("MAX_WORKERS","3"))),
      max_escalations=int(settings.get("max_escalations",os.getenv("MAX_ESCALATIONS","1"))),
      max_retries_per_call=int(settings.get("max_retries_per_call",os.getenv("MAX_RETRIES_PER_CALL","1"))),
      call_timeout_seconds=float(settings.get("call_timeout_seconds",os.getenv("CALL_TIMEOUT_SECONDS","45"))),
      retry_base_seconds=float(settings.get("retry_base_seconds",os.getenv("RETRY_BASE_SECONDS","1"))),
      retry_max_seconds=float(settings.get("retry_max_seconds",os.getenv("RETRY_MAX_SECONDS","60"))),
    )

def budget_settings(budget):
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

COMPARE_METRIC_FIELDS=(
    "agent_executions","logical_calls","physical_requests","input_tokens",
    "output_tokens","total_tokens","e2e_ms","retries","escalations","calculated_cost_usd",
)

def comparison_metrics(metrics=None, *, e2e_ms=None):
    metrics=metrics if isinstance(metrics,dict) else {}
    result={key:metrics.get(key) for key in COMPARE_METRIC_FIELDS}
    if e2e_ms is not None and result["e2e_ms"] is None:
        result["e2e_ms"]=e2e_ms
    usage_available=metrics.get("usage_metadata_available")
    if usage_available is None:
        # Preserve compatibility with older execution payloads that only had
        # positive token counters, while treating zero-only legacy values as
        # unavailable rather than claiming a measured zero/cost.
        usage_available=any(
            isinstance(metrics.get(key),(int,float)) and metrics.get(key)>0
            for key in ("input_tokens","output_tokens","total_tokens")
        ) or None
    if usage_available is not True:
        for key in ("input_tokens","output_tokens","total_tokens","calculated_cost_usd"):
            result[key]=None
    result["usage_metadata_available"]=usage_available
    result["pricing_model"]=metrics.get("pricing_model")
    result["e2e_boundary_version"] = metrics.get("e2e_boundary_version", "E2E-MEASURE-V2")
    result["context_prep_ms"] = metrics.get("context_prep_ms")
    return result

def format_history(history,max_chars:int=10000):
    if not history:return ""
    lines=[]; used=0
    # Keep the most recent dialogue, but do not let a long transcript silently
    # dominate the structural analysis prompt.
    for item in reversed(history[-12:]):
        content=str(item.get("content") or "").strip()
        if not content: continue
        line=f"{item.get('role')}: {content[:3000]}"
        if lines and used+len(line)+1>max_chars: break
        if not lines and len(line)>max_chars: line=line[:max_chars]
        lines.append(line); used+=len(line)+1
    return "\n".join(reversed(lines))

def task_with_history(message,history):
    # Backwards-compatible helper used in evidence/older tests. The actual
    # RunState keeps the current task and recent conversation context separate.
    chat=format_history(history)
    return message if not chat else message+"\n\nRECENT CHAT:\n"+chat

def _apply_run_metadata(data,run_metadata):
    """Copy safe experiment-control metadata without exposing credentials."""
    if run_metadata is None:
        return data
    metadata=deepcopy(run_metadata)
    data["pilot"]=metadata
    data["dry_run"]=bool(metadata.get("dry_run",False))
    data["phase"]=metadata.get("phase", "DRY_RUN" if data["dry_run"] else "PILOT")
    data["research_evidence"]=bool(metadata.get("research_evidence",data["phase"]=="PILOT" and not data["dry_run"]))
    data["evidence_class"]=metadata.get("evidence_class", "DRY_RUN" if data["dry_run"] else data["phase"])
    for key in (
        "condition_id","attempt_id","pilot_manifest_id","run_manifest_hash",
        "unit_id","task_id","repeat_index","execution_order",
        "benchmark_version","rubric_version_reference","context_snapshot_id",
        "context_snapshot_hash","provider_error_category","provider_error_message",
        "incident_category","incident_origin","outcome_category","incident_taxonomy_version",
        "freeze_identity","unit_attempt_id",
    ):
        if metadata.get(key) is not None:
            data[key]=deepcopy(metadata[key])
    if metadata.get("config_identities") is not None:
        data["config_identities"]=deepcopy(metadata["config_identities"])
    if metadata.get("pilot_config_identities") is not None:
        data["pilot_config_identities"]=deepcopy(metadata["pilot_config_identities"])
    if metadata.get("provider_incident") is True:
        data["provider_incident"]=True
    if metadata.get("provider_error_category") is not None:
        data["provider_error_category"]=metadata["provider_error_category"]
    if metadata.get("provider_error_message") is not None:
        data["provider_error_message"]=metadata["provider_error_message"]
    status=data.get("status")
    # A degraded verifier is not automatically a provider incident.  The
    # structured runtime incident decides whether the origin was provider,
    # verifier/infrastructure, or strategy validation.
    if metadata.get("incident") is not None and isinstance(metadata.get("incident"), dict):
        data["incident"] = deepcopy(metadata["incident"])
        data["incident_category"] = metadata["incident"].get("category")
        data["incident_origin"] = metadata["incident"].get("origin")
        data["incident_taxonomy_version"] = metadata["incident"].get("taxonomy_version", INCIDENT_TAXONOMY_VERSION)
        if metadata["incident"].get("origin") == "provider":
            data["provider_incident"] = True
            data["provider_error_category"] = metadata["incident"].get("provider_error_category")
            data["provider_error_message"] = metadata["incident"].get("safe_message")
    elif metadata.get("incident_records") is not None:
        records = [item for item in metadata.get("incident_records", []) if isinstance(item, dict)]
        if records:
            data["incidents"] = deepcopy(records)
            data["incident"] = deepcopy(records[-1])
            data["incident_category"] = records[-1].get("category")
            data["incident_origin"] = records[-1].get("origin")
            data["incident_taxonomy_version"] = records[-1].get("taxonomy_version", INCIDENT_TAXONOMY_VERSION)
            if records[-1].get("origin") == "provider":
                data["provider_incident"] = True
                data["provider_error_category"] = records[-1].get("provider_error_category")
                data["provider_error_message"] = records[-1].get("safe_message")
    if data.get("outcome_category") is None:
        if status == "completed" and data.get("answer"):
            data["outcome_category"] = "SUCCESS"
        elif data.get("incident_category"):
            data["outcome_category"] = data["incident_category"]
        elif data.get("stop_reason") == "STOP_VERIFICATION_UNAVAILABLE":
            data["outcome_category"] = "EXPERIMENT_INFRASTRUCTURE_ERROR"
        elif status in {"failed", "stopped", "degraded"}:
            data["outcome_category"] = "STRATEGY_TERMINAL_FAILURE"
        else:
            data["outcome_category"] = "SUCCESS"
    data["run_state"]=(
        "PROVIDER_ERROR" if data.get("provider_incident") else
        "COMPLETED" if status=="completed" else
        "STOPPED" if status=="stopped" else
        "FAILED" if status in {"failed","degraded"} else status
    )
    data["pilot"]["run_state"]=data["run_state"]
    if data.get("provider_incident"):
        data["pilot"]["provider_incident"]=True
    if data.get("provider_error_category") is not None:
        data["pilot"]["provider_error_category"]=data["provider_error_category"]
    if data.get("provider_error_message") is not None:
        data["pilot"]["provider_error_message"]=data["provider_error_message"]
    data["pilot"]["outcome_category"] = data.get("outcome_category")
    if data.get("incident_category") is not None:
        data["pilot"]["incident_category"] = data["incident_category"]
    return data

def save(data):
    RUNS.mkdir(parents=True,exist_ok=True)
    path=RUNS/f"{data['run_id']}.json"
    temporary=path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temporary,path)

def save_failed_run_evidence(*,strategy,provider,model,message,context,retrieval_meta,history,error,
                             comparison_meta=None,e2e_ms=None,budget_config=None,run_id=None,
                             run_metadata=None,incident=None,context_prep_ms=None):
    """Persist a compare run even when provider construction fails before RunState."""
    run_id=run_id or f"run_{uuid.uuid4().hex[:12]}"
    if incident is None:
        incident = (
            safe_runtime_incident(
                category="INVALID_INPUT_OR_SCOPE",
                safe_message=str(getattr(error, "detail", "Invalid request")),
                provider=provider,
                model=model,
                origin="input",
            )
            if isinstance(error, HTTPException)
            else safe_provider_incident(error, provider=provider, model=model)
        )
    safe_error=incident.get("safe_message") or "Provider execution failed."
    data={
      "run_id":run_id,"strategy":strategy,"provider":provider,"model":model,
      "user_message":message,"created_at":int(time.time()),"task":message,
      "chat_history":format_history(history),"context":context,
      "retrieval_meta":deepcopy(retrieval_meta),"events":[],
      "snapshot_id":retrieval_meta.get("snapshot_id"),
      "snapshot_hash":retrieval_meta.get("snapshot_hash"),
      "context_hash":retrieval_meta.get("context_hash"),
      "source_document_ids":retrieval_meta.get("source_document_ids",[]),
      "chunk_ids":retrieval_meta.get("chunk_ids",[]),"answer":"",
      "status":"failed","stop_reason":"STOP_FAILURE","error":safe_error,
      "metrics":comparison_metrics({"context_prep_ms":context_prep_ms},e2e_ms=e2e_ms),
      "incident":deepcopy(incident),
      "incidents":[deepcopy(incident)],
      "incident_category":incident.get("category"),
      "incident_origin":incident.get("origin"),
      "incident_taxonomy_version":incident.get("taxonomy_version", INCIDENT_TAXONOMY_VERSION),
      "outcome_category":incident.get("category") or "PROVIDER_ERROR",
    }
    config_identity=strategy_config_identity(
        strategy,make_budget(budget_config),retrieval_meta=retrieval_meta,
    )
    data.update({
      "strategy_config_id":config_identity.get("strategy_config_id"),
      "strategy_config_version":config_identity.get("strategy_config_version"),
      "config_identity":config_identity,
    })
    _apply_run_metadata(data,run_metadata)
    if comparison_meta is not None: data["comparison"]=deepcopy(comparison_meta)
    save(data)
    return data

def conversation_path(conversation_id):
    if not re.fullmatch(r"chat_[A-Za-z0-9_-]+",conversation_id):
        raise HTTPException(400,"Invalid conversation id")
    return CONVERSATIONS/f"{conversation_id}.json"

def new_conversation_id(): return f"chat_{uuid.uuid4().hex[:12]}"

def read_conversation(conversation_id):
    path=conversation_path(conversation_id)
    if not path.exists(): return None
    return json.loads(path.read_text(encoding="utf-8"))

def write_conversation(data):
    # Replace in one operation so a browser refresh cannot observe a half-written
    # transcript (and a concurrent request cannot leave invalid JSON behind).
    path=conversation_path(data["conversation_id"])
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temporary,path)

def history_from_conversation(data):
    return [{"role":m.get("role"),"content":m.get("content","")} for m in data.get("messages",[])
            if m.get("role") in {"user","assistant"} and m.get("content")]

def run_mode(data):
    for event in data.get("events",[]):
        if event.get("title") in {"AUTO route selected","Static route frozen"}:
            return (event.get("meta") or {}).get("mode") or event.get("detail")
    return None

def conversation_turns(data):
    messages=data.get("messages",[])
    turns=[]; pending=None
    for message in messages:
        if message.get("role")=="user":
            if pending: turns.append(pending)
            pending={"user":message,"assistant":None}
        elif message.get("role")=="assistant":
            if pending is None: pending={"user":None,"assistant":message}
            else: pending["assistant"]=message
            turns.append(pending); pending=None
    if pending: turns.append(pending)
    return turns

def append_turn(conversation_id,*,message,data,context):
    now=int(time.time())
    conversation=read_conversation(conversation_id) or {
      "conversation_id":conversation_id,"title":message[:72],"created_at":now,"messages":[],"run_ids":[]}
    conversation["updated_at"]=now
    conversation["provider"]=data.get("provider")
    conversation["model"]=data.get("model")
    conversation["context"]=context
    conversation["status"]=data.get("status")
    answer=data.get("answer","") or (
      f"Không thể nhận câu trả lời từ {data.get('provider','provider')}: "
      f"{data.get('error') or 'provider request failed'}"
    )
    conversation["messages"].extend([
      {"role":"user","content":message,"run_id":data.get("run_id"),"created_at":now},
      {"role":"assistant","content":answer,
       "run_id":data.get("run_id"),"status":data.get("status"),"stop_reason":data.get("stop_reason"),
       "provider":data.get("provider"),"model":data.get("model"),"mode":run_mode(data),
       "metrics":data.get("metrics") or {},"created_at":now},
    ])
    conversation["run_ids"].append(data.get("run_id"))
    write_conversation(conversation)
    return conversation

def append_failed_turn(conversation_id,*,message,provider,model,error,context,run_id):
    """Persist failures that happen before Orchestrator can emit a final event.

    A failed provider request is still a turn in the user's conversation. Keeping
    it here lets the UI retain the conversation ID and show the next attempt in
    the same transcript instead of silently starting a new chat.
    """
    now=int(time.time())
    conversation=read_conversation(conversation_id) or {
      "conversation_id":conversation_id,"title":message[:72],"created_at":now,"messages":[],"run_ids":[]}
    conversation["updated_at"]=now
    conversation["provider"]=provider
    conversation["model"]=model
    conversation["context"]=context
    conversation["status"]="failed"
    conversation["last_error"]=error
    conversation["messages"].extend([
      {"role":"user","content":message,"run_id":run_id,"created_at":now},
      {"role":"assistant","content":f"Không thể nhận câu trả lời từ {provider}: {error or 'provider request failed'}.","run_id":run_id,
       "status":"failed","stop_reason":"STOP_FAILURE","provider":provider,"model":model,
       "error":error,"mode":None,"metrics":{},"created_at":now},
    ])
    conversation["run_ids"].append(run_id)
    write_conversation(conversation)
    return conversation

def provider_configured(name):
    if name=="fake": return True
    return bool(os.getenv(f"{name.upper()}_API_KEY"))

def provider_key_fingerprint(name):
    """One-way local fingerprint used only to invalidate stale API-test badges."""
    if name=="fake": return "fake"
    key=os.getenv(f"{name.upper()}_API_KEY","")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else None

def read_provider_status():
    try: data=json.loads(PROVIDER_STATUS.read_text(encoding="utf-8"))
    except Exception: data={}
    result={"fake":{"status":"ready","model":"fake-research-v2",
                     "error_category":"SUCCESS",
                     "safe_message":"Fake provider generation is available locally."}}
    defaults,_=model_catalog()
    for name in ("gemini","groq","openrouter","openai"):
        if not provider_configured(name):
            result[name]={"status":"missing","model":None,
                          "error_category":"NOT_CONFIGURED",
                          "safe_message":SAFE_MESSAGES["NOT_CONFIGURED"]}
            continue
        saved=data.get(name) if isinstance(data,dict) else None
        # Never carry a green "verified" badge across a changed API key.
        if (not isinstance(saved,dict)
                or saved.get("key_fingerprint")!=provider_key_fingerprint(name)
                or saved.get("model")!=defaults.get(name)):
            result[name]={"status":"unknown","model":None,
                          "error_category":None,
                          "safe_message":"No live provider check is recorded for the current key/model."}
            continue
        result[name]={k:v for k,v in saved.items() if k!="key_fingerprint"}
    return result

def write_provider_status(name,status=None,model=None,error=None,diagnostic=None):
    try: data=json.loads(PROVIDER_STATUS.read_text(encoding="utf-8"))
    except Exception: data={}
    if diagnostic is not None:
        category=diagnostic.get("error_category")
        data[name]={**diagnostic,
                    "status":"ready" if category=="SUCCESS" else "failed",
                    "model":model,
                    "error":diagnostic.get("safe_message"),
                    "checked_at":int(time.time()),
                    "key_fingerprint":provider_key_fingerprint(name)}
    else:
        # Backwards-compatible path for existing local status files/tests.
        category="SUCCESS" if status=="ready" else None
        data[name]={"status":status,"model":model,"error":redact_secrets(error) if error else None,
                    "error_category":category,
                    "safe_message":redact_secrets(error) if error else None,
                    "checked_at":int(time.time()),"key_fingerprint":provider_key_fingerprint(name)}
    PROVIDER_STATUS.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

async def execute_once(*,strategy,provider_name,model_name=None,message,frozen_context,retrieval_meta,history,emit,
                       conversation_id=None,budget_config=None,comparison_meta=None,run_id=None,
                       run_metadata=None,generation_settings=None,e2e_started_at=None,request_gate=None):
    accepted_started = float(e2e_started_at) if e2e_started_at is not None else time.perf_counter()
    model=validated_model(provider_name,model_name)
    p=get_provider(provider_name,model=model,generation_settings=generation_settings)
    async def enriched_emit(event):
        if event.get("type")=="final":
            event={**event,"conversation_id":conversation_id,"provider":p.name,"model":p.model}
        await emit(event)
    state=RunState(strategy=strategy,provider=p.name,model=p.model,task=message,
                   context=frozen_context,chat_history=format_history(history),retrieval_meta=retrieval_meta,
                   run_id=run_id or f"run_{uuid.uuid4().hex[:12]}",
                   started_at=accepted_started)
    orch=Orchestrator(
        p,
        enriched_emit,
        budget=make_budget(budget_config),
        request_gate=request_gate,
    ); await orch.run(state)
    data={"run_id":state.run_id,"strategy":state.strategy,"provider":state.provider,"model":state.model,
          "conversation_id":conversation_id,"user_message":message,"created_at":int(time.time()),
          "task":state.task,"chat_history":state.chat_history,"context":state.context,"retrieval_meta":state.retrieval_meta,"events":state.events,
          "snapshot_id":state.retrieval_meta.get("snapshot_id"),
          "snapshot_hash":state.retrieval_meta.get("snapshot_hash"),
          "context_hash":state.retrieval_meta.get("context_hash"),
          "source_document_ids":state.retrieval_meta.get("source_document_ids",[]),
          "chunk_ids":state.retrieval_meta.get("chunk_ids",[]),
          "answer":state.answer,"status":state.status,"stop_reason":state.stop_reason,
          "error":state.error or None,"metrics":orch.metrics(state),
          "incidents":deepcopy(state.incident_records),
          "incident":deepcopy(state.incident_records[-1]) if state.incident_records else None,
          "incident_category":state.incident_records[-1].get("category") if state.incident_records else None,
          "incident_origin":state.incident_records[-1].get("origin") if state.incident_records else None,
          "incident_taxonomy_version":INCIDENT_TAXONOMY_VERSION,
          "outcome_category":state.outcome_category,
           "strategy_config_id":state.config_identity.get("strategy_config_id"),
           "strategy_config_version":state.config_identity.get("strategy_config_version"),
           "config_identity":deepcopy(state.config_identity)}
    if isinstance(generation_settings,dict):
        # Persist only the non-secret settings identity and request controls;
        # provider credentials and clients never enter run evidence.
        safe_settings = {
            key: deepcopy(generation_settings[key])
            for key in (
                "model_settings_id", "model_settings_version",
                "provider_adapter", "request_parameters", "provider_timeout_seconds",
                "sdk_max_retries",
            )
            if key in generation_settings
        }
        if safe_settings:
            data["model_settings"] = safe_settings
    if run_metadata is not None:
        metadata=deepcopy(run_metadata)
        if state.incident_records:
            metadata["incident_records"] = deepcopy(state.incident_records)
            metadata["incident"] = deepcopy(state.incident_records[-1])
        if state.outcome_category:
            metadata["outcome_category"] = state.outcome_category
        _apply_run_metadata(data,metadata)
    if comparison_meta is not None: data["comparison"]=deepcopy(comparison_meta)
    save(data); return data

@app.get("/")
async def home(): return FileResponse(BASE/"static"/"index.html")

@app.get("/api/health")
async def health(): return {"status":"ok","service":"adaptive-agent-lab","version":APP_VERSION}

@app.get("/api/config")
async def config():
    models,model_options=model_catalog()
    configured={name:provider_configured(name) for name in models}
    requested=os.getenv("DEFAULT_PROVIDER","fake")
    default_provider=requested if configured.get(requested) else next((name for name in ("groq","openrouter","gemini","openai","fake") if configured.get(name)),"fake")
    return {"default_provider":default_provider,"models":models,"model_options":model_options,
            "available":configured,"configured":configured,"provider_status":read_provider_status(),
            "chat_strategy":"adaptive-auto","app_version":APP_VERSION}

@app.post("/api/provider/test")
@app.post("/api/provider/diagnostic")
async def provider_test(payload:ProviderTestRequest):
    configured=provider_configured(payload.provider)
    model=None
    if configured:
        try:
            model=validated_model(payload.provider,payload.model)
        except HTTPException:
            diagnostic=diagnostic_for_category(payload.provider,True,"MODEL_NOT_FOUND",latency_ms=0,preflight=True)
            write_provider_status(payload.provider,model=payload.model,diagnostic=diagnostic)
            return diagnostic
    elif payload.provider=="fake":
        model=validated_model(payload.provider,payload.model)

    diagnostic=await run_provider_diagnostic(
        provider_name=payload.provider,
        configured=configured,
        model=model,
        provider_factory=get_provider,
        timeout_seconds=make_budget().call_timeout_seconds,
    )
    write_provider_status(payload.provider,model=model,diagnostic=diagnostic)
    return diagnostic

@app.get("/api/runs")
async def list_runs(limit:int=14):
    rows=[]
    for path in sorted(RUNS.glob("run_*.json"),key=lambda p:p.stat().st_mtime,reverse=True)[:max(1,min(limit,50))]:
        try:
            d=json.loads(path.read_text(encoding="utf-8"))
            rows.append({"run_id":d.get("run_id"),"strategy":d.get("strategy"),"provider":d.get("provider"),
              "model":d.get("model"),"status":d.get("status"),"stop_reason":d.get("stop_reason"),
              "task_preview":(d.get("task") or "").split("\n\nRECENT CHAT:")[0][:90],"metrics":d.get("metrics",{})})
        except: pass
    return {"runs":rows}

@app.get("/api/conversations")
async def list_conversations(limit:int=30):
    rows=[]
    paths=sorted(CONVERSATIONS.glob("chat_*.json"),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in paths[:max(1,min(limit,100))]:
        try:
            d=json.loads(path.read_text(encoding="utf-8")); messages=d.get("messages",[])
            last_user=next((m.get("content","") for m in reversed(messages) if m.get("role")=="user"),"")
            rows.append({"conversation_id":d.get("conversation_id"),"title":d.get("title") or "Cuộc trò chuyện",
              "updated_at":d.get("updated_at"),"provider":d.get("provider"),"model":d.get("model"),
              "status":d.get("status"),"message_count":len(messages),
              "turn_count":sum(1 for m in messages if m.get("role")=="user"),
              "run_count":len(d.get("run_ids",[])),"last_preview":last_user[:120]})
        except Exception: pass
    return {"conversations":rows}

@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id:str):
    data=read_conversation(conversation_id)
    if not data: raise HTTPException(404,"Conversation not found")
    return {**data,"turns":conversation_turns(data)}

class ConversationUpdate(BaseModel):
    title:str=Field(min_length=1,max_length=100)

@app.patch("/api/conversations/{conversation_id}")
async def rename_conversation(conversation_id:str,payload:ConversationUpdate):
    data=read_conversation(conversation_id)
    if not data: raise HTTPException(404,"Conversation not found")
    data["title"]=payload.title.strip()
    data["updated_at"]=int(time.time())
    write_conversation(data)
    return {"ok":True,"conversation_id":conversation_id,"title":data["title"]}

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id:str):
    data=read_conversation(conversation_id)
    if not data: raise HTTPException(404,"Conversation not found")
    for run_id in data.get("run_ids",[]):
        if isinstance(run_id,str) and re.fullmatch(r"run_[A-Za-z0-9_-]+",run_id):
            try:(RUNS/f"{run_id}.json").unlink(missing_ok=True)
            except Exception:pass
    conversation_path(conversation_id).unlink(missing_ok=True)
    return {"ok":True,"conversation_id":conversation_id}

@app.get("/api/runs/{run_id}")
async def get_run(run_id:str):
    if not re.fullmatch(r"run_[A-Za-z0-9_-]+",run_id): raise HTTPException(400,"Invalid run id")
    p=RUNS/f"{run_id}.json"
    if not p.exists(): raise HTTPException(404,"Run not found")
    return json.loads(p.read_text(encoding="utf-8"))

@app.post("/api/chat/stream")
async def chat(payload:ChatRequest):
    async def gen():
        q=asyncio.Queue()
        async def emit(x): await q.put(x)
        conversation_id=payload.conversation_id or new_conversation_id()
        existing=read_conversation(conversation_id)
        stored_history=history_from_conversation(existing) if existing else payload.history
        # Preserve a conversation's context when an API client omits the field;
        # an explicitly supplied empty string still intentionally clears it.
        context = payload.context if "context" in payload.model_fields_set else (
            (existing or {}).get("context", "")
        )
        accepted_started=time.perf_counter()
        snapshot,meta=frozen_snapshot(payload.message,context)
        meta=deepcopy(meta)
        meta["context_prep_ms"] = round((time.perf_counter()-accepted_started)*1000)
        async def work():
            try:
                data=await execute_once(strategy="adaptive",provider_name=payload.provider,model_name=payload.model,
                    message=payload.message,frozen_context=snapshot,retrieval_meta=meta,
                    history=stored_history,emit=emit,conversation_id=conversation_id,
                    e2e_started_at=accepted_started)
                append_turn(conversation_id,message=payload.message,data=data,context=context)
            except Exception as exc:
                incident=(safe_runtime_incident(
                    category="INVALID_INPUT_OR_SCOPE",
                    safe_message=str(getattr(exc, "detail", "Invalid request")),
                    provider=payload.provider,
                    model=payload.model or "unknown",
                    origin="input",
                ) if isinstance(exc, HTTPException) else safe_provider_incident(
                    exc,provider=payload.provider,model=payload.model or "unknown"
                ))
                safe_error=incident.get("safe_message") or "Provider execution failed."
                run_id=f"run_{uuid.uuid4().hex[:12]}"
                # execute_once can fail before a RunState exists (bad model or
                # missing API key). Save an evidence record and failed turn so a
                # retry remains attached to this conversation.
                failed={"run_id":run_id,"strategy":"adaptive","provider":payload.provider,
                        "model":payload.model,"conversation_id":conversation_id,
                        "user_message":payload.message,"created_at":int(time.time()),
                        "task":payload.message,"chat_history":format_history(stored_history),
                        "context":snapshot,"retrieval_meta":meta,"events":[],"answer":"",
                        "snapshot_id":meta.get("snapshot_id"),"snapshot_hash":meta.get("snapshot_hash"),
                        "context_hash":meta.get("context_hash"),
                        "source_document_ids":meta.get("source_document_ids",[]),
                        "chunk_ids":meta.get("chunk_ids",[]),
                        "status":"failed","stop_reason":"STOP_FAILURE","error":safe_error,
                        "metrics":{"e2e_ms":round((time.perf_counter()-accepted_started)*1000),
                                   "e2e_boundary_version":"E2E-MEASURE-V2",
                                   "context_prep_ms":meta.get("context_prep_ms")},
                        "incident":incident,"incidents":[incident],
                        "incident_category":incident.get("category"),
                        "incident_origin":incident.get("origin"),
                        "incident_taxonomy_version":incident.get("taxonomy_version",INCIDENT_TAXONOMY_VERSION),
                        "outcome_category":incident.get("category")}
                failed_config=strategy_config_identity(
                    "adaptive",make_budget(),retrieval_meta=meta,
                )
                failed.update({
                    "strategy_config_id":failed_config.get("strategy_config_id"),
                    "strategy_config_version":failed_config.get("strategy_config_version"),
                    "config_identity":failed_config,
                })
                try:
                    save(failed)
                    append_failed_turn(conversation_id,message=payload.message,
                        provider=payload.provider,model=payload.model,error=safe_error,
                        context=context,run_id=run_id)
                except Exception:
                    # Never replace the original provider error with a storage
                    # error while streaming the fatal contract event.
                    pass
                await q.put({"type":"fatal","error":safe_error,"run_id":run_id,
                             "conversation_id":conversation_id,"provider":payload.provider,
                             "model":payload.model})
            finally: await q.put(None)
        t=asyncio.create_task(work())
        try:
            while True:
                x=await q.get()
                if x is None: break
                yield json.dumps(x,ensure_ascii=False)+"\n"
        finally: await t
    return StreamingResponse(gen(),media_type="application/x-ndjson")

@app.post("/api/compare/stream")
async def compare(payload:CompareRequest):
    async def gen():
        accepted_started=time.perf_counter()
        snapshot,meta=frozen_snapshot(payload.message,payload.context) # one frozen snapshot for all 4
        meta=deepcopy(meta)
        meta["context_prep_ms"] = round((time.perf_counter()-accepted_started)*1000)
        frozen_provider=payload.provider
        try:
            frozen_model=validated_model(frozen_provider,payload.model)
        except Exception:
            # Keep the requested value stable so all four failures describe the
            # same invalid configuration instead of re-reading environment state.
            frozen_model=payload.model
        budget_template=make_budget()
        frozen_budget=budget_settings(budget_template)
        comparison_id=f"cmp_{uuid.uuid4().hex[:12]}"
        frozen_settings={"provider":frozen_provider,"model":frozen_model,
                         "budget":frozen_budget,
                         "model_config_id":MODEL_CONFIG_ID,
                         "model_settings_id":MODEL_SETTINGS_ID,
                         "price_config_id":PRICE_CONFIG_ID,
                         "rag_config_id":meta.get("retrieval_config_id","RAG-LEXICAL-V1"),
                         "retrieval_settings":deepcopy(meta.get("retrieval_settings") or {})}
        for order,strategy in enumerate(("single","fixed","static","adaptive"),1):
            comparison_meta={"comparison_id":comparison_id,"order":order,"total":4,
                             "provider":frozen_provider,"model":frozen_model,
                             "settings":deepcopy(frozen_settings),
                             "e2e_boundary_version":"E2E-MEASURE-V2",
                             "context_prep_ms":meta.get("context_prep_ms")}
            strategy_started=time.perf_counter()
            # Attribute the shared context preparation to every strategy
            # without charging the time spent in earlier strategies.
            strategy_e2e_started=strategy_started-(float(meta.get("context_prep_ms") or 0)/1000.0)
            yield json.dumps({"type":"compare_start","strategy":strategy,
                              "order":order,"comparison_id":comparison_id,
                              "snapshot_id":meta.get("snapshot_id"),
                              "snapshot_hash":meta.get("snapshot_hash"),
                              "provider":frozen_provider,"model":frozen_model},ensure_ascii=False)+"\n"
            async def sink(_): pass
            try:
                d=await execute_once(strategy=strategy,provider_name=frozen_provider,model_name=frozen_model,
                  message=payload.message,frozen_context=snapshot,retrieval_meta=deepcopy(meta),history=payload.history,
                  emit=sink,budget_config=frozen_budget,comparison_meta=comparison_meta,
                  e2e_started_at=strategy_e2e_started)
                result={"run_id":d["run_id"],"strategy":strategy,"status":d["status"],
                  "stop_reason":d["stop_reason"],"answer":d.get("answer") or None,
                  "metrics":comparison_metrics(d.get("metrics")),"quality_evaluation":"Not evaluated",
                  "provider":d.get("provider",frozen_provider),"model":d.get("model",frozen_model),
                  "strategy_config_id":d.get("strategy_config_id"),
                  "strategy_config_version":d.get("strategy_config_version"),
                  "config_identity":deepcopy(d.get("config_identity") or {}),
                  "snapshot_id":d.get("snapshot_id"),"snapshot_hash":d.get("snapshot_hash"),
                  "context_hash":d.get("context_hash"),"comparison":comparison_meta}
                if d.get("error"): result["error"]=redact_secrets(d.get("error"))
                yield json.dumps({"type":"compare_result","result":result},ensure_ascii=False)+"\n"
            except Exception as exc:
                # Keep the comparison provenance and a distinct raw run even
                # when provider/model construction fails before RunState exists.
                failed=save_failed_run_evidence(strategy=strategy,provider=frozen_provider,model=frozen_model,
                  message=payload.message,context=snapshot,retrieval_meta=meta,history=payload.history,error=exc,
                  comparison_meta=comparison_meta,e2e_ms=round((time.perf_counter()-strategy_e2e_started)*1000),
                  budget_config=frozen_budget,context_prep_ms=meta.get("context_prep_ms"))
                yield json.dumps({"type":"compare_result","result":{"run_id":failed["run_id"],
                  "strategy":strategy,"status":"failed","stop_reason":"STOP_FAILURE","answer":None,
                  "metrics":failed["metrics"],"quality_evaluation":"Not evaluated",
                  "provider":frozen_provider,"model":frozen_model,"error":failed["error"],
                  "strategy_config_id":failed.get("strategy_config_id"),
                  "strategy_config_version":failed.get("strategy_config_version"),
                  "config_identity":deepcopy(failed.get("config_identity") or {}),
                  "snapshot_id":meta.get("snapshot_id"),"snapshot_hash":meta.get("snapshot_hash"),
                  "context_hash":meta.get("context_hash"),"comparison":comparison_meta}},ensure_ascii=False)+"\n"
        yield json.dumps({"type":"compare_final","comparison_id":comparison_id,
                          "provider":frozen_provider,"model":frozen_model,"settings":frozen_settings,
                          "snapshot_id":meta.get("snapshot_id"),
                          "snapshot_hash":meta.get("snapshot_hash"),
                          "context_hash":meta.get("context_hash")},ensure_ascii=False)+"\n"
    return StreamingResponse(gen(),media_type="application/x-ndjson")
