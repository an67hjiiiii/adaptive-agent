const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const svgIcon = (name,className="") => `<svg class="ui-icon ${className}" aria-hidden="true"><use href="#${name==="chat"?"ui-message":`i-${name}`}"></use></svg>`;
const app = $("#app"), messages = $("#messages"), promptEl = $("#prompt"), sendBtn = $("#send"), trace = $("#trace");
let cfg = null, history = [], busy = false, currentRunId = null, currentConversationId = null;
let rawEvents = [], compareBusy = false, currentMode = null, currentRequestedMode = "adaptive-auto", liveTurn = null, currentRunEvidence = null, currentMetrics = {};
let conversationCache = [], pendingDeleteConversation = null, pendingRenameConversation = null, activeContextFile = null;
let contextAttachments = new Map(), contextAttachmentSequence = 0, persistedContextSources = [];
let compareResults = new Map(), compareSnapshotId = null, contextReturnFocus = null;
const ACTIVE_CONVERSATION_KEY = "adaptive.activeConversation.v5";
const INSPECTOR_TAB_KEY = "adaptive.inspectorTab";
let modalReturnFocus = null;
const MAX_CONTEXT_FILE_BYTES_V1 = 100000;
const CONTEXT_STATUS_TEXT = Object.freeze({loading:"Đang tải",processing:"Đang xử lý",ready:"Sẵn sàng",unsupported:"Không hỗ trợ",error:"Không thể xử lý"});

// Product mode is independent from provider/model selection.  AUTO is the
// controller route; explicit modes only force topology and never rewrite the
// selected provider or model.
function mapUiModeToChatStrategy(value){
  const raw=String(value||"auto").trim().toLowerCase();
  if(raw==="auto")return "adaptive-auto";
  return ({"adaptive-auto":"adaptive-auto",adaptive:"adaptive-auto",direct:"DIRECT",parallel:"PARALLEL",planned:"PLANNED"})[raw]||null;
}

function safeFrontendEvidence(value){
  const blocked=/^(api[_-]?key|authorization|secret|password|hidden[_-]?rubric|rubric|evaluator|research_annotations)$/i;
  if(Array.isArray(value))return value.map(safeFrontendEvidence);
  if(value&&typeof value==="object")return Object.fromEntries(Object.entries(value).filter(([key])=>!blocked.test(key)).map(([key,item])=>[key,safeFrontendEvidence(item)]));
  return value;
}

// UI-only vocabulary. Internal enum values, IDs and raw evidence stay unchanged.
const UI_TEXT = Object.freeze({
  labels: Object.freeze({
    adaptiveAuto: "Tự động",
    adaptiveOrchestrator: "Bộ điều phối thích ứng",
    controller: "Bộ điều phối",
    agentExecution: "Lượt Agent",
    logicalCall: "Lượt gọi mô hình",
    physicalRequest: "Yêu cầu API",
    provider: "Nhà cung cấp",
    model: "Mô hình",
    context: "Ngữ cảnh",
    frozenContext: "Ngữ cảnh đã đóng băng",
    copy: "Sao chép",
    viewExecution: "Chi tiết xử lý",
    unavailable: "Không có dữ liệu",
    notEvaluated: "Chưa đánh giá"
  }),
  modes: Object.freeze({
    DIRECT: "Trực tiếp",
    PARALLEL: "Song song",
    PLANNED: "Theo kế hoạch",
    AUTO: "Tự động"
  }),
  strategies: Object.freeze({
    single: "Single (một lượt)",
    fixed: "Fixed (topology cố định)",
    static: "Static (preset cố định)",
    adaptive: "Adaptive"
  }),
  roles: Object.freeze({
    Analyzer: "Agent phân tích",
    Planner: "Agent lập kế hoạch",
    Worker: "Agent xử lý",
    Synthesizer: "Agent tổng hợp",
    Verifier: "Agent kiểm tra",
    "Runtime Verifier": "Agent kiểm tra",
    "Direct Solver": "Agent xử lý trực tiếp"
  }),
  statuses: Object.freeze({
    PASS: "Đạt",
    FAIL: "Không đạt",
    NEEDS_WORK: "Cần bổ sung",
    STOP_SUFFICIENT: "Đã đủ yêu cầu",
    STOP_FAILURE: "Dừng do lỗi",
    STOP_BUDGET_OR_VERIFICATION: "Dừng do ngân sách hoặc kiểm chứng",
    STOP_VERIFICATION_UNAVAILABLE: "Dừng vì Agent kiểm tra không khả dụng",
    STOP_BUDGET_LOGICAL_CALLS: "Dừng do vượt lượt gọi",
    STOP_BUDGET_PHYSICAL_REQUESTS: "Dừng do vượt yêu cầu API",
    running: "Đang chạy",
    completed: "Hoàn thành",
    failed: "Thất bại",
    degraded: "Cần xem lại",
    stopped: "Đã dừng",
    pending: "Đang chờ",
    idle: "Chưa chạy",
    UNKNOWN: "Chưa rõ",
    UNAVAILABLE: "Không có dữ liệu"
  }),
  eventTitles: Object.freeze({
    "Run started": "Bắt đầu lượt chạy",
    "Run failed": "Lượt chạy thất bại",
    "Structural signals": "Tín hiệu cấu trúc",
    "Agent selection": "Chọn Agent",
    "AUTO route selected": "Đã chọn tuyến AUTO",
    "DAG validated": "Đã kiểm tra DAG",
    "Planner proposal": "Đề xuất từ Planner",
    "Parallel plan from structural aspects": "Kế hoạch song song từ cấu trúc",
    "Fixed topology frozen": "Đã cố định topology Fixed",
    "Fixed worker slots": "Các vị trí Worker của Fixed",
    "Static route frozen": "Đã cố định tuyến Static",
    "Static preset worker slots": "Các vị trí Worker của preset Static",
    "Static verifier observed": "Verifier của Static đã kiểm tra",
    "Frozen Context Snapshot": "Ngữ cảnh đã đóng băng",
    "Targeted escalation": "Bổ sung xử lý có mục tiêu",
    "Early stop after escalation": "Dừng sớm sau bổ sung xử lý",
    "Runtime Verifier unavailable": "Agent kiểm tra không khả dụng",
    "Ready-set batch": "Nhóm ready-set",
    "Ready-set scheduler": "Bộ lập lịch theo phụ thuộc",
    "Verifier": "Agent kiểm tra",
    "Analyzer": "Agent phân tích",
    "Planner": "Agent lập kế hoạch",
    "Synthesizer": "Agent tổng hợp"
  })
});
function modeText(value){const raw=String(value||"");if(raw==="adaptive-auto"||raw.toLowerCase()==="auto")return UI_TEXT.modes.AUTO;return UI_TEXT.modes[raw]||String(value||"—")}
function strategyText(value){return UI_TEXT.strategies[String(value||"")]||String(value||"—")}
function statusText(value){return UI_TEXT.statuses[String(value||"")]||String(value||"—")}
function stopText(value){const raw=String(value||"");return UI_TEXT.statuses[raw]||UI_TEXT.eventTitles[raw]||phraseText(raw)||"—"}
function demandText(value){const raw=String(value||"");return ({low:"Thấp (low)",medium:"Trung bình (medium)",high:"Cao (high)"}[raw]||raw||"—")}
function providerText(value){return ({fake:"Fake",gemini:"Gemini",openai:"OpenAI",groq:"Groq",openrouter:"OpenRouter"}[String(value||"")]||cap(value))}
function roleText(value){
  const raw=String(value||"").trim();
  if(UI_TEXT.roles[raw])return UI_TEXT.roles[raw];
  const worker=raw.match(/^Worker\s*[·:]\s*(.+)$/i);
  if(worker)return `Agent xử lý ${worker[1]}`;
  const verifier=raw.match(/^(?:Runtime\s+)?Verifier\s*[·:]\s*(.+)$/i);
  if(verifier)return `Agent kiểm tra ${verifier[1]}`;
  return raw;
}
function eventTitleText(value){return UI_TEXT.eventTitles[String(value||"")]||roleText(value)||String(value||"")}
function phraseText(value){
  let text=String(value??"");
  const replacements=[
    ["Logical call", "Lượt gọi Model logic"], ["provider request", "request API thực tế"],
    ["attempt", "lần thử"], ["Completed in", "Hoàn thành sau"], ["in \d+ ms", null],
    ["dependency and/or high verification demand", "có phụ thuộc hoặc yêu cầu kiểm chứng cao"],
    ["multiple relatively independent aspects", "nhiều phần tương đối độc lập"],
    ["single-focus or no useful decomposition", "một trọng tâm hoặc không cần tách nhỏ"],
    ["Kahn cycle check passed", "đã kiểm tra chu trình Kahn"], ["node\(s\)", "nút"],
    ["aspect\(s\)", "khía cạnh"], ["dependency edge\(s\)", "cạnh phụ thuộc"],
    ["verification=", "kiểm chứng="], ["Targeted repair passed", "bổ sung có mục tiêu đã đạt"],
    ["retry", "thử lại"], ["No output recorded.", "Chưa ghi nhận đầu ra."],
    ["Triggered by a missing verifier issue.", "Được kích hoạt bởi vấn đề Verifier còn thiếu."],
    ["Resolve verifier issue", "Xử lý vấn đề do Verifier nêu"],
    ["Extract aspects, dependencies, parallelizability, verification demand and rationale", "Trích xuất khía cạnh, phụ thuộc, khả năng song song, mức yêu cầu kiểm chứng và lý giải"],
    ["Build and validate the smallest useful dependency DAG", "Dựng và kiểm tra DAG phụ thuộc nhỏ gọn nhất"],
    ["Combine bounded worker results into one candidate answer", "Kết hợp kết quả Worker có giới hạn thành câu trả lời dự kiến"],
    ["Answer the original task from frozen context", "Trả lời task gốc từ ngữ cảnh đã đóng băng"],
    ["Solve the requested aspect", "Xử lý khía cạnh được yêu cầu"],
    ["Complete the assigned evidence pass for the original task", "Hoàn tất lượt kiểm tra evidence được giao cho task gốc"],
    ["Complete the assigned evidence pass", "Hoàn tất lượt kiểm tra evidence được giao"],
    ["policy/routing", "chính sách/định tuyến"], ["runtime", "runtime"], ["controller", "bộ điều phối"]
  ];
  for(const [from,to] of replacements){if(to===null)continue;text=text.replace(new RegExp(from,"gi"),to)}
  text=text.replace(/\bDIRECT\b/g,"Trực tiếp").replace(/\bPARALLEL\b/g,"Song song").replace(/\bPLANNED\b/g,"Theo kế hoạch");
  text=text.replace(/\bPASS\b/g,"Đạt").replace(/\bNEEDS_WORK\b/g,"Cần bổ sung").replace(/\bFAIL\b/g,"Không đạt").replace(/\bSTOP_SUFFICIENT\b/g,"Đã đủ yêu cầu");
  return text;
}
function unavailableText(){return UI_TEXT.labels.unavailable}

function rememberConversation(id){if(id)localStorage.setItem(ACTIVE_CONVERSATION_KEY,id);else localStorage.removeItem(ACTIVE_CONVERSATION_KEY)}
function esc(value){return String(value ?? "").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
function inline(value){return esc(value).replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/__(.+?)__/g,"<strong>$1</strong>").replace(/\*([^*\n]+)\*/g,"<em>$1</em>")}
function markdown(value){
  const lines=String(value ?? "").replace(/<br\s*\/?>/gi,"\n").replace(/\r/g,"").split("\n");let html="",paragraph=[],list=null,inCode=false,code=[];
  const flush=()=>{if(paragraph.length){html+=`<p>${paragraph.map(inline).join("<br>")}</p>`;paragraph=[]}};
  const closeList=()=>{if(list){html+=`</${list}>`;list=null}};
  for(const line of lines){
    if(line.trim().startsWith("```")){flush();closeList();if(inCode){html+=`<pre><code>${esc(code.join("\n"))}</code></pre>`;code=[];inCode=false}else inCode=true;continue}
    if(inCode){code.push(line);continue} if(!line.trim()){flush();closeList();continue}
    const heading=line.match(/^(#{1,4})\s+(.+)$/);if(heading){flush();closeList();const level=Math.min(heading[1].length+1,4);html+=`<h${level}>${inline(heading[2])}</h${level}>`;continue}
    const bullet=line.match(/^\s*[-*]\s+(.+)$/),num=line.match(/^\s*\d+[.)]\s+(.+)$/);if(bullet||num){flush();const next=bullet?"ul":"ol";if(list!==next){closeList();list=next;html+=`<${list}>`}html+=`<li>${inline((bullet||num)[1])}</li>`;continue}
    const quote=line.match(/^>\s?(.+)$/);if(quote){flush();closeList();html+=`<blockquote>${inline(quote[1])}</blockquote>`;continue} paragraph.push(line)
  }
  if(inCode)html+=`<pre><code>${esc(code.join("\n"))}</code></pre>`;flush();closeList();return html||"<p>(Không có nội dung.)</p>"
}
function safeErrorDetail(value){
  const raw=String(value||"").trim();
  try{const parsed=JSON.parse(raw);return String(parsed.detail||parsed.error||raw)}catch{return raw}
}
function friendlyRunError(value,provider,model){
  const detail=safeErrorDetail(value);
  if(/Unsupported model selection/i.test(detail))return `### Không thể chạy với mô hình này\n\nMô hình **${model||"đang chọn"}** không được ${providerText(provider)} hỗ trợ.\n\nHãy chọn mô hình khác trong menu bên dưới ô chat rồi thử lại.`;
  if(/Failed to fetch|NetworkError|network request failed/i.test(detail))return "### Không thể kết nối tới server local\n\nServer chưa phản hồi yêu cầu.\n\nHãy kiểm tra server đang chạy rồi thử lại.";
  return `### Không thể hoàn thành lượt chạy\n\n${detail||"Lượt chạy đã dừng trước khi tạo được câu trả lời."}`
}
function cap(s){return String(s||"").charAt(0).toUpperCase()+String(s||"").slice(1)}
function toast(msg,type=""){const d=document.createElement("div");d.className=`toast ${type}`;d.textContent=msg;$("#toasts").appendChild(d);setTimeout(()=>d.remove(),4200)}
function scrollBottom(){messages.scrollTop=messages.scrollHeight}
function autoSize(){promptEl.style.height="auto";promptEl.style.height=Math.min(promptEl.scrollHeight,180)+"px"}
function fmtTime(epoch){if(!epoch)return "";try{return new Intl.DateTimeFormat("vi-VN",{hour:"2-digit",minute:"2-digit",day:"2-digit",month:"2-digit"}).format(new Date(epoch*1000))}catch{return ""}}
function fmtLatency(ms){if(ms==null)return "—";return ms>=1000?(ms/1000).toFixed(1)+"s":ms+"ms"}

function updatePanelButtons(){
  const sideCollapsed=app.classList.contains("side-collapsed");
  const sideToggle=$("#sidebarToggle");
  if(sideToggle){sideToggle.setAttribute("aria-expanded",String(!sideCollapsed));sideToggle.setAttribute("aria-label",sideCollapsed?"Mở lịch sử":"Thu gọn lịch sử");sideToggle.title=sideCollapsed?"Mở lịch sử":"Thu gọn lịch sử"}
  const inspectorOpen=innerWidth<=900?app.classList.contains("mobile-ins-open"):!app.classList.contains("ins-collapsed");
  const inspectorToggle=$("#inspectorToggle");
  if(inspectorToggle){inspectorToggle.setAttribute("aria-expanded",String(inspectorOpen));inspectorToggle.setAttribute("aria-label",inspectorOpen?"Ẩn quá trình xử lý":"Hiện quá trình xử lý");inspectorToggle.title=inspectorOpen?"Ẩn quá trình xử lý":"Hiện quá trình xử lý"}
  const mobileSidebar=$("#mobileSidebar"),mobileSideOpen=app.classList.contains("mobile-side-open");
  if(mobileSidebar){mobileSidebar.setAttribute("aria-expanded",String(mobileSideOpen));mobileSidebar.setAttribute("aria-label",mobileSideOpen?"Đóng lịch sử":"Mở lịch sử");mobileSidebar.title=mobileSideOpen?"Đóng lịch sử":"Mở lịch sử"}
}
function persistPanels(){
  localStorage.setItem("adaptive.sideCollapsed",app.classList.contains("side-collapsed")?"1":"0");
  localStorage.setItem("adaptive.insCollapsed",app.classList.contains("ins-collapsed")?"1":"0");
  localStorage.setItem("adaptive.mobileInspectorOpen",app.classList.contains("mobile-ins-open")?"1":"0");
  updatePanelButtons();
}
function restorePanels(){
  app.classList.toggle("side-collapsed",localStorage.getItem("adaptive.sideCollapsed")==="1");
  const inspectorPreference=localStorage.getItem("adaptive.insCollapsed");app.classList.toggle("ins-collapsed",inspectorPreference===null||inspectorPreference==="1");
  if(innerWidth<=900&&localStorage.getItem("adaptive.mobileInspectorOpen")==="1")app.classList.add("mobile-ins-open");
  updatePanelButtons();
}

function selectedModel(){return $("#model").value}
const FALLBACK_PRODUCT_MODES=Object.freeze([
  {id:"adaptive-auto",label:"Tự động"},
  {id:"DIRECT",label:"Trực tiếp"},
  {id:"PARALLEL",label:"Song song"},
  {id:"PLANNED",label:"Theo kế hoạch"},
]);
function selectedMode(){
  const saved=localStorage.getItem("adaptive.mode"),configured=cfg?.default_mode||"adaptive-auto";
  return mapUiModeToChatStrategy(saved||configured)||"adaptive-auto";
}
function productModeOptions(){return Array.isArray(cfg?.mode_options)&&cfg.mode_options.length?cfg.mode_options:FALLBACK_PRODUCT_MODES}
function updateModeDisplay(){
  const mode=selectedMode(),item=productModeOptions().find(option=>option.id===mode);
  const summary=$("#settingsModeSummary");if(summary)summary.textContent=item?.label||modeText(mode);
  const badge=$("#modelModeBadge");if(badge)badge.textContent=item?.label||modeText(mode);
}
function modelTierText(value){return ({recommended:"Đề xuất",balanced:"Cân bằng",economy:"Tiết kiệm",quality:"Chất lượng cao",fast:"Nhanh",faster:"Nhanh hơn",general:"Đa dụng",offline:"Ngoại tuyến","dev-only":"Thử nghiệm"}[String(value||"")]||cap(value))}
function positionModelMenu(){const menu=$("#modelMenu"),button=$("#modelMenuButton");if(!menu?.classList.contains("open")||!button)return;const rect=button.getBoundingClientRect(),gap=8,width=menu.offsetWidth,height=menu.offsetHeight;menu.style.left=Math.max(10,Math.min(innerWidth-width-10,rect.left))+"px";menu.style.top=Math.max(10,rect.top-height-gap)+"px"}
function renderModelPicker(){if(!cfg)return;const provider=$("#provider").value,model=selectedModel(),mode=selectedMode(),providers=$("#providerChoices"),models=$("#modelChoices"),modes=$("#modeChoices");if(!providers||!models)return;
  providers.innerHTML=Object.keys(cfg.models).map(key=>`<button type="button" class="provider-choice${key===provider?" selected":""}" role="tab" aria-selected="${key===provider}" data-provider="${esc(key)}" ${cfg.available[key]?"":"disabled"}><span>${esc(providerText(key))}</span>${key===provider?svgIcon("check","small"):""}</button>`).join("");
  const items=cfg.model_options?.[provider]||[];models.innerHTML=items.length?items.map(item=>`<button type="button" class="model-choice${item.id===model?" selected":""}" role="option" aria-selected="${item.id===model}" data-model="${esc(item.id)}"><span><b>${esc(item.label)}</b><small>${esc(modelTierText(item.tier))}</small></span>${item.id===model?svgIcon("check","small"):""}</button>`).join(""):'<div class="model-empty">Provider này chưa có model khả dụng.</div>';
  if(modes)modes.innerHTML=productModeOptions().map(item=>`<button type="button" class="mode-choice${item.id===mode?" selected":""}" role="radio" aria-checked="${item.id===mode}" data-mode="${esc(item.id)}"><span><b>${esc(item.label)}</b></span>${item.id===mode?svgIcon("check","small"):""}</button>`).join("");
  $$("#providerChoices .provider-choice").forEach(button=>button.onclick=()=>{$("#provider").value=button.dataset.provider;localStorage.setItem("adaptive.provider",button.dataset.provider);populateModels();requestAnimationFrame(positionModelMenu)});
  $$("#modelChoices .model-choice").forEach(button=>button.onclick=()=>{$("#model").value=button.dataset.model;localStorage.setItem(`adaptive.model.${provider}`,button.dataset.model);updateProviderDisplay();closeFloatingUi();$("#modelMenuButton").focus()})
  $$("#modeChoices .mode-choice").forEach(button=>button.onclick=()=>{const selected=mapUiModeToChatStrategy(button.dataset.mode)||"adaptive-auto";localStorage.setItem("adaptive.mode",selected);currentRequestedMode=selected;updateModeDisplay();renderModelPicker();closeFloatingUi();$("#modelMenuButton").focus()})
}
function populateModels(preferred=null){
  const provider=$("#provider").value,select=$("#model"),items=cfg?.model_options?.[provider]||[];
  const saved=localStorage.getItem(`adaptive.model.${provider}`),target=preferred||saved||cfg?.models?.[provider];select.innerHTML="";
  items.forEach(item=>{const o=document.createElement("option");o.value=item.id;o.textContent=item.label;o.dataset.tier=item.tier;select.appendChild(o)});if(items.some(x=>x.id===target))select.value=target;select.disabled=items.length<=1;updateProviderDisplay();updateModeDisplay()
}
function selectionStatus(){
  const provider=$("#provider").value,record=cfg?.provider_status?.[provider],model=selectedModel();
  if(provider==="fake")return "ready";if(!cfg?.available?.[provider])return "missing";
  if(record?.model && record.model!==model)return "unknown";return record?.status||"unknown"
}
function updateProviderDisplay(){
  if(!cfg)return;const provider=$("#provider").value,status=selectionStatus(),model=selectedModel()||cfg.models[provider],record=cfg?.provider_status?.[provider];$("#insProvider").textContent=providerText(provider);
  const labels={ready:"Đã xác minh API",failed:"Lần kiểm tra gần nhất thất bại",unknown:"Chưa kiểm tra",missing:"Chưa cấu hình khóa API"};$("#providerState").textContent=provider==="fake"?"Bản demo ngoại tuyến":labels[status]||statusText(status);$("#providerState").title=record?.safe_message||"";
  $("#providerState").className="status-chip"+(provider!=="fake"&&status==="ready"?" connected":status==="failed"?" failed":"");$("#providerCheck").className="provider-check"+(provider==="fake"?"":status==="ready"?" ok":status==="failed"||status==="missing"?" bad":"");
  $("#providerCheck").title=status==="ready"?`Đã xác minh ${model}`:`Kiểm tra ${providerText(provider)} · ${model}`;const item=(cfg.model_options?.[provider]||[]).find(x=>x.id===model);$("#modelName").textContent=item?.label||model;const summary=$("#settingsModelSummary");if(summary)summary.textContent=`${providerText(provider)} · ${item?.label||model}`;renderModelPicker()
}
async function loadConfig(){
  const response=await fetch("/api/config");if(!response.ok)throw new Error(`Config error (${response.status})`);cfg=await response.json();
  const contextFile=$("#contextFile"),extensions=Array.isArray(cfg.context_file_extensions)?cfg.context_file_extensions:[];
  if(contextFile&&extensions.length)contextFile.accept=extensions.map(extension=>"."+extension).join(",");
  const select=$("#provider");select.innerHTML="";Object.keys(cfg.models).forEach(provider=>{const o=document.createElement("option");o.value=provider;o.textContent=providerText(provider);o.disabled=!cfg.available[provider];select.appendChild(o)});
  const saved=localStorage.getItem("adaptive.provider"),preferred=(saved&&cfg.available[saved])?saved:cfg.default_provider;select.value=cfg.available[preferred]?preferred:"fake";populateModels()
}

function clearWelcome(){document.querySelector(".welcome")?.remove()}
function makeTurnCard(userText,{createdAt=null,pending=false}={}){
  clearWelcome();const card=document.createElement("article");card.className="turn-card";
  card.innerHTML=`<div class="turn-question"><div class="turn-label"><b>Bạn</b><span class="turn-time">${esc(fmtTime(createdAt))}</span></div><div class="question-text">${esc(userText)}</div></div><div class="turn-answer"><div class="answer-head"><div class="avatar">${svgIcon("agent")}</div><div class="answer-head-copy"><b>Adaptive Agent</b><span class="answer-meta">${UI_TEXT.labels.adaptiveAuto}</span></div><span class="mode-pill">${pending?"Đang xử lý":modeText("AUTO")}</span></div><div class="answer-body">${pending?'<div class="answer-pending"><span class="pulse"></span><span>Đang phân tích task và điều phối Agent…</span></div>':""}</div><div class="turn-footer"></div></div>`;
  messages.appendChild(card);scrollBottom();return card
}
function setTurnAnswer(card,text,meta={}){
  if(!card)return;const body=card.querySelector(".answer-body"),pill=card.querySelector(".mode-pill"),head=card.querySelector(".answer-meta"),footer=card.querySelector(".turn-footer");body.innerHTML=markdown(text);body.classList.toggle("error-answer",meta.status==="failed");if(meta.status==="failed")body.setAttribute("role","alert");else body.removeAttribute("role");
  const mode=meta.mode||"AUTO";pill.textContent=meta.status==="failed"?statusText("FAIL"):meta.status==="degraded"?statusText("degraded"):modeText(mode);card.classList.toggle("failed",meta.status==="failed");card.classList.toggle("degraded",meta.status==="degraded");head.textContent=meta.model||UI_TEXT.labels.adaptiveAuto;
  footer.innerHTML="";const m=meta.metrics||{},summary=document.createElement("div"),actions=document.createElement("div");summary.className="run-summary-line";actions.className="turn-actions";
  const details=[m.agent_executions!=null&&`${m.agent_executions} Agent`,m.logical_calls!=null&&`${m.logical_calls} lượt gọi`,m.total_tokens!=null&&`${Number(m.total_tokens).toLocaleString()} token`,m.e2e_ms!=null&&fmtLatency(m.e2e_ms)].filter(Boolean);
  const showStop=meta.status==="failed"||meta.status==="degraded";
  summary.innerHTML=`<b>${esc(modeText(mode))}</b>${details.length?` · ${esc(details.join(" · "))}`:""}${showStop&&meta.stopReason?` · <span class="run-stop">${esc(stopText(meta.stopReason))}</span>`:""}`;
  const sources=(Array.isArray(meta.sources)?meta.sources:[]).map(source=>typeof source==="string"?source:source?.filename).filter(Boolean);
  if(sources.length){const sourceBox=document.createElement("div");sourceBox.className="turn-sources";sourceBox.innerHTML=`<span class="source-label">Nguồn</span>${sources.map(source=>`<span class="source-chip">${svgIcon("file","small")}${esc(source)}</span>`).join("")}`;footer.appendChild(sourceBox)}
  const copy=document.createElement("button");copy.className="mini-action";copy.innerHTML=`${svgIcon("copy","small")}<span>${UI_TEXT.labels.copy}</span>`;copy.onclick=()=>navigator.clipboard.writeText(text||"").then(()=>toast("Đã sao chép","success"));actions.appendChild(copy);
  if(meta.status==="failed"){
    const retry=document.createElement("button");retry.className="mini-action retry-turn";retry.textContent="Thử lại";retry.setAttribute("aria-label","Thử lại câu hỏi của lượt chạy thất bại");retry.onclick=()=>{const original=card.querySelector(".question-text")?.textContent?.trim();if(!original||busy)return;promptEl.value=original;autoSize();runChat()};actions.appendChild(retry)
  }
  if(meta.runId){const run=document.createElement("button");run.className="run-pill";run.innerHTML=`${svgIcon("info","small")}<span>Chi tiết xử lý</span>`;run.setAttribute("aria-label","Xem quá trình xử lý và evidence của lượt này");run.title="Mở Chi tiết xử lý";run.onclick=()=>{openInspector();loadRunInspector(meta.runId)};actions.appendChild(run);const compare=document.createElement("button");compare.className="mini-action compare-turn";compare.innerHTML=`${svgIcon("compare","small")}<span>So sánh</span>`;compare.onclick=openCompare;actions.appendChild(compare);card.dataset.runId=meta.runId}
  footer.append(summary,actions)
}
function renderTurn(turn,conversation){
  const user=turn.user||{},assistant=turn.assistant||{};const card=makeTurnCard(user.content||"(Không có câu hỏi)",{createdAt:user.created_at});setTurnAnswer(card,assistant.content||"(Chưa có câu trả lời)",{runId:assistant.run_id,provider:assistant.provider||conversation.provider,model:assistant.model||conversation.model,status:assistant.status,stopReason:assistant.stop_reason,mode:assistant.mode,requestedMode:assistant.requested_mode||assistant.processing_mode||conversation.processing_mode,metrics:assistant.metrics,sources:assistant.sources||assistant.context_sources||[]});return card
}
function fallbackTurns(messagesList){const turns=[];let pending=null;for(const m of messagesList||[]){if(m.role==="user"){if(pending)turns.push(pending);pending={user:m,assistant:null}}else if(m.role==="assistant"){if(!pending)pending={user:null,assistant:m};else pending.assistant=m;turns.push(pending);pending=null}}if(pending)turns.push(pending);return turns}

function resetSnapshot(){
  const box=$("#contextProvenance");if(!box)return;box.hidden=true;$("#contextSummary").textContent="";$("#contextChunks").innerHTML="";
}
function renderSnapshot(meta){
  const box=$("#contextProvenance"),summary=$("#contextSummary"),chunks=$("#contextChunks");
  if(!box||!meta?.snapshot_id){resetSnapshot();return}
  box.hidden=false;
  const trunc=meta.truncation?.applied?`<div class="context-warning">Đã cắt ${Number(meta.truncation.dropped_chars||0).toLocaleString()} ký tự theo giới hạn snapshot.</div>`:"";
  const attached=(Array.isArray(meta.attached_sources)?meta.attached_sources:[]).map(source=>typeof source==="string"?source:source?.filename).filter(Boolean);
  const docs=(attached.length?attached:meta.source_document_ids||[]).join(", ")||"(không có)";
  summary.innerHTML=`<b>${esc(meta.snapshot_id)}</b><div>Mã băm ngữ cảnh: <code>${esc(meta.context_hash||meta.snapshot_hash||"—")}</code></div><div>Tài liệu nguồn: <code>${esc(docs)}</code> · ${meta.chunks_selected??0}/${meta.chunks_total??0} đoạn</div>${trunc}`;
  const selected=meta.selected_chunks||[];
  chunks.innerHTML=selected.length?selected.map((chunk,index)=>`<article class="context-chunk"><header><b>${esc(chunk.chunk_id||`chunk-${index+1}`)}</b><span>vị trí ${Number(chunk.index??index)}</span></header><pre>${esc(chunk.text||"")}</pre></article>`).join(""):"<div class=\"context-empty\">Không có đoạn nguồn được chọn.</div>";
}
function resetInspector(mode="running"){
  trace.innerHTML=mode==="idle"?'<div class="empty">Chọn một lượt chạy trong hội thoại để xem luồng thực thi.</div>':"";rawEvents=[];currentRunEvidence=null;currentMetrics={};$("#rawEvents").textContent="[]";$("#insMode").textContent="—";currentMode=null;currentRequestedMode=selectedMode();updateModeDisplay();resetSnapshot();
  ["mAgents","mCalls","mRequests","mEsc"].forEach(id=>$("#"+id).textContent="0");["mInputTokens","mOutputTokens","mTokens","mRetries","mCost","mLatency"].forEach(id=>$("#"+id).textContent="—");$("#autoExplain").innerHTML='<b>Chế độ tự động</b><span>Adaptive Agent sẽ tự chọn cách xử lý phù hợp cho từng lượt.</span>';
  $("#runState").textContent=mode==="idle"?statusText("idle"):statusText("running");$("#runState").className=`run-state ${mode}`
  renderEvidencePanels();
}
function appendTrace(e){
  const d=document.createElement("div");d.className=`trace-item ${e.kind||""}`;d.innerHTML=`<b>${esc(eventTitleText(e.title))}</b><p>${esc(phraseText(e.detail||""))}</p><time>${e.t_ms||0}ms</time>`;trace.appendChild(d);
  if(e.kind==="rag"&&e.meta)renderSnapshot(e.meta);
  if(e.meta?.mode){currentMode=e.meta.mode;$("#insMode").textContent=modeText(currentMode)}
  if(e.title==="AUTO route selected"||e.title==="Product mode selected"){const agents=e.meta?.selected_agents||{};const automatic=e.title==="AUTO route selected";$("#autoExplain").innerHTML=`<b>${automatic?"Tự động chọn":"Đã cố định mode"} → ${esc(modeText(e.detail))}</b><span>${esc(phraseText(e.meta?.why||e.detail||""))} · ${Object.entries(agents).filter(x=>x[1]).map(x=>roleText(x[0])+" × "+x[1]).join(" · ")}</span>`}
}
function traceEvent(e){rawEvents.push(e);if(!currentRunEvidence)currentRunEvidence={strategy:"adaptive",events:rawEvents};else currentRunEvidence.events=rawEvents;$("#rawEvents").textContent=JSON.stringify(safeFrontendEvidence(rawEvents),null,2);appendTrace(e);renderEvidencePanels();trace.scrollTop=trace.scrollHeight}
function renderMetrics(m){if(!m)return;currentMetrics=m;if(currentRunEvidence)currentRunEvidence.metrics=m;$("#mAgents").textContent=m.agent_executions??0;$("#mCalls").textContent=m.logical_calls??0;$("#mRequests").textContent=m.physical_requests??0;const inputValue=m.input_tokens==null?"Unavailable":Number(m.input_tokens).toLocaleString(),outputValue=m.output_tokens==null?"Unavailable":Number(m.output_tokens).toLocaleString(),totalValue=m.total_tokens==null?"Unavailable":Number(m.total_tokens).toLocaleString(),latencyValue=m.e2e_ms==null?"Unavailable":fmtLatency(m.e2e_ms),retryValue=m.retries==null?"Unavailable":Number(m.retries).toLocaleString();$("#mInputTokens").textContent=inputValue==="Unavailable"?unavailableText():inputValue;$("#mOutputTokens").textContent=outputValue==="Unavailable"?unavailableText():outputValue;$("#mTokens").textContent=totalValue==="Unavailable"?unavailableText():totalValue;$("#mLatency").textContent=latencyValue==="Unavailable"?unavailableText():latencyValue;$("#mRetries").textContent=retryValue==="Unavailable"?unavailableText():retryValue;$("#mEsc").textContent=m.escalations??0;$("#mCost").textContent=m.calculated_cost_usd==null?unavailableText():"$"+Number(m.calculated_cost_usd).toFixed(6);renderEvidencePanels()}

function displayText(value,limit=420){return esc(String(value??"").replace(/\s+/g," ").trim().slice(0,limit))}
function displayList(values,empty="—",className="evidence-chips"){
  const items=(values||[]).filter(value=>value!==null&&value!==undefined&&String(value).trim()!=="");
  return items.length?`<div class="${className}">${items.map(value=>`<span>${displayText(value,180)}</span>`).join("")}</div>`:`<span class="muted-value">${empty}</span>`
}
function eventLogicalCall(event){const value=event?.meta?.logical_call; if(value!=null)return value;const found=String(event?.detail||"").match(/Logical call #(\d+)/i);return found?Number(found[1]):null}
function fallbackGoal(agentType){return ({
  "Analyzer":"Trích xuất tín hiệu cấu trúc của task",
  "Planner":"Dựng và kiểm tra DAG phụ thuộc",
  "Worker":"Xử lý phần việc được giao",
  "Synthesizer":"Kết hợp kết quả giới hạn thành câu trả lời dự kiến",
  "Verifier":"Kiểm tra câu trả lời đã đủ và đưa ra phán định",
  "Direct Solver":"Trả lời task gốc từ ngữ cảnh đã đóng băng",
  "Runtime Verifier":"Kiểm tra câu trả lời đã đủ và đưa ra phán định"
}[agentType]||"Thực hiện vai trò runtime có giới hạn")}
function evidenceModel(){
  const run=currentRunEvidence||{},events=Array.isArray(run.events)?run.events:rawEvents;
  const model={run,events,analysis:null,mode:run.mode||run.processing_mode||null,why:"",selection:{},planEvents:[],batches:[],escalations:[],verifications:[],stop:null,agents:[],metrics:Object.keys(currentMetrics||{}).length?currentMetrics:(run.metrics||{})};
  const byId=new Map(),pendingByRole=new Map();let fallbackIndex=0;
  const roleFor=(event,meta)=>String(meta.role||event.title||"Agent");
  const ensureAgent=(event,id,meta)=>{
    const role=roleFor(event,meta),agentType=String(meta.agent_type||role.split(" · ",1)[0]||"Agent");
    let agent=byId.get(id);
    if(!agent){
      agent={id,logicalCall:eventLogicalCall(event),role,agentType,assignedGoal:meta.assigned_goal||fallbackGoal(agentType),dependencies:Array.isArray(meta.dependencies)?meta.dependencies.slice():[],subtaskId:meta.subtask_id||null,targetedRepair:Boolean(meta.targeted_repair)||String(meta.subtask_id||"").startsWith("T"),escalationIssue:meta.escalation_issue||"",startMs:meta.start_ms??event.t_ms??null,endMs:null,durationMs:null,provider:meta.provider||run.provider||"—",model:meta.model||run.model||"—",inputTokens:null,outputTokens:null,totalTokens:null,status:meta.status||"running",outputPreview:"",requests:0,attempts:[]};
      byId.set(id,agent);model.agents.push(agent)
    }
    agent.logicalCall=agent.logicalCall??eventLogicalCall(event);agent.role=role||agent.role;agent.agentType=agentType||agent.agentType;
    if(meta.assigned_goal)agent.assignedGoal=meta.assigned_goal;if(Array.isArray(meta.dependencies))agent.dependencies=meta.dependencies.slice();
    if(meta.subtask_id)agent.subtaskId=meta.subtask_id;if(meta.targeted_repair!=null)agent.targetedRepair=Boolean(meta.targeted_repair);
    if(meta.escalation_issue)agent.escalationIssue=meta.escalation_issue;if(meta.provider)agent.provider=meta.provider;if(meta.model)agent.model=meta.model;
    return agent
  };
  const idFor=(event,meta)=>{
    if(meta.execution_id)return String(meta.execution_id);
    const role=roleFor(event,meta),pending=pendingByRole.get(role);if(pending)return pending.id;
    fallbackIndex+=1;return `AE-${String(fallbackIndex).padStart(3,"0")}`
  };
  for(const event of events){
    if(!event||typeof event!=="object")continue;const meta=event.meta&&typeof event.meta==="object"?event.meta:{};
    if(event.kind==="analysis"&&Array.isArray(meta.aspects))model.analysis=meta;
    if(event.title==="AUTO route selected"||event.title==="Product mode selected"){model.mode=event.detail||meta.mode||model.mode;model.why=meta.why||""}
    if(event.kind==="agent_selection")model.selection=meta;
    if(event.kind==="plan"&&Array.isArray(meta.subtasks))model.planEvents.push({title:event.title,subtasks:meta.subtasks,meta,event});
    if(event.kind==="scheduler"&&Array.isArray(meta.nodes))model.batches.push({nodes:meta.nodes.slice(),parallel:Boolean(meta.parallel)});
    if(event.title==="Targeted escalation")model.escalations.push({issues:Array.isArray(meta.issues)?meta.issues:[],subtasks:Array.isArray(meta.subtasks)?meta.subtasks:[],round:meta.round||model.escalations.length+1});
    if(event.kind==="verification")model.verifications.push({status:String(meta.status||event.title||"").replace(/^.*·\s*/,""),issues:Array.isArray(meta.issues)?meta.issues:[],rationale:meta.rationale||event.detail||"",targetedRepair:Boolean(meta.targeted_repair)});
    if(event.kind==="stop")model.stop=event;
    if(event.kind==="agent_start"){
      const id=idFor(event,meta),agent=ensureAgent(event,id,meta);agent.startMs=meta.start_ms??event.t_ms??agent.startMs;agent.status=meta.status||"running";pendingByRole.set(roleFor(event,meta),agent)
    }else if(event.kind==="agent_end"||event.kind==="agent_error"){
      const id=idFor(event,meta),agent=ensureAgent(event,id,meta),ended=meta.end_ms??event.t_ms??null;agent.endMs=ended;agent.durationMs=meta.duration_ms??(ended!=null&&agent.startMs!=null?Math.max(0,ended-agent.startMs):null);agent.status=meta.status||(event.kind==="agent_error"?"failed":"completed");agent.provider=meta.provider||agent.provider;agent.model=meta.model||agent.model;agent.inputTokens=meta.input_tokens??agent.inputTokens;agent.outputTokens=meta.output_tokens??agent.outputTokens;agent.totalTokens=meta.total_tokens??meta.tokens??agent.totalTokens;agent.outputPreview=meta.output_preview||meta.error||event.detail||agent.outputPreview;pendingByRole.set(roleFor(event,meta),agent)
    }else if(event.kind==="provider_request"){
      const id=idFor(event,meta),agent=ensureAgent(event,id,meta);agent.requests+=1;agent.attempts.push(meta.attempt??agent.requests)
    }
  }
  const primaryPlan=model.planEvents.find(item=>item.title==="DAG validated")||model.planEvents[0];model.subtasks=primaryPlan?.subtasks||[];model.subtaskMap=new Map(model.subtasks.map(item=>[String(item.id),item]));
  for(const agent of model.agents){
    const subtask=agent.subtaskId&&model.subtaskMap.get(String(agent.subtaskId));
    if(subtask){agent.assignedGoal=agent.assignedGoal||subtask.goal;agent.dependencies=Array.isArray(subtask.depends_on)?subtask.depends_on.slice():agent.dependencies}
    if(agent.targetedRepair&&!agent.escalationIssue){const index=Number(String(agent.subtaskId||"").replace(/^T/,""))-1,issue=model.escalations.at(-1)?.issues?.[index];agent.escalationIssue=issue?.target||issue?.description||"Verifier issue"}
  }
  if(!Object.keys(model.selection).length){const counts={};for(const agent of model.agents){const key=agent.agentType.toLowerCase().replace(/\s+/g,"_");counts[key]=(counts[key]||0)+1}model.selection=counts}
  const batchBySubtask=new Map();model.batches.forEach((batch,index)=>batch.nodes.forEach(id=>batchBySubtask.set(String(id),{index:index+1,parallel:batch.parallel})));for(const agent of model.agents){const batch=agent.subtaskId&&batchBySubtask.get(String(agent.subtaskId));if(batch){agent.batch=batch.index;agent.parallelBatch=batch.parallel}}
  model.stopReason=run.stop_reason||model.stop?.title||"—";model.status=run.status||"running";return model
}

function switchInspectorTab(name){
  const button=$(`.ins-tab[data-tab="${name}"]`);if(!button)return;
  $$('.ins-tab').forEach(item=>{const active=item===button;item.classList.toggle("active",active);item.setAttribute("aria-selected",String(active));item.tabIndex=active?0:-1});
  $$('.ins-panel').forEach(panel=>panel.classList.toggle("active",panel.id===`tab-${name}`));
  localStorage.setItem(INSPECTOR_TAB_KEY,name);
}
function openInspector(){if($("#compareModal")?.classList.contains("open"))closeCompare();if(innerWidth<=900)app.classList.add("mobile-ins-open");else app.classList.remove("ins-collapsed");persistPanels();}
function closeInspector(){if(innerWidth<=900)app.classList.remove("mobile-ins-open");else app.classList.add("ins-collapsed");persistPanels()}
function selectionLabel(key){return ({direct_solver:"Agent xử lý trực tiếp",planner:"Agent lập kế hoạch",workers:"Agent xử lý",verifier:"Agent kiểm tra",synthesizer:"Agent tổng hợp",analyzer:"Agent phân tích"}[key]||key.replace(/_/g," "))}
function renderOverview(model){
  const box=$("#overviewContent");if(!box)return;const a=model.analysis||{},aspects=Array.isArray(a.aspects)?a.aspects:[],deps=Array.isArray(a.dependencies)?a.dependencies:[],groups=Array.isArray(a.parallelizable_groups)?a.parallelizable_groups:[],reasons=Array.isArray(a.verification_reasons)?a.verification_reasons:[];
  const aspectItems=aspects.map((item,index)=>typeof item==="object"?`${item.name||`Khía cạnh ${index+1}`} · ${item.goal||""}`:String(item));
  const dependencyItems=deps.map(item=>typeof item==="object"?`${item.from||"?"} → ${item.to||"?"}${item.reason?` · ${phraseText(item.reason)}`:""}`:String(item));
  const groupItems=groups.map((group,index)=>`Nhóm ${index+1}: ${(Array.isArray(group)?group:[]).join(" + ")}`);
  const roles=Object.entries(model.selection||{}).filter(([,count])=>Number(count)>0).map(([key,count])=>`${selectionLabel(key)} × ${count}`);
  const agentCount=model.agents.length,logical=model.metrics?.logical_calls??model.agents.filter(item=>item.logicalCall!=null).length,physical=model.metrics?.physical_requests??model.agents.reduce((sum,item)=>sum+item.requests,0);
  const verdicts=model.verifications.map(item=>`${item.targetedRepair?"Kiểm tra lại":"Agent kiểm tra"}: ${statusText(item.status||"UNKNOWN")}`);
  box.innerHTML=`<div class="overview-controller"><div class="controller-mark">◎</div><div><b>${UI_TEXT.labels.adaptiveOrchestrator}</b><span>Bộ điều khiển chính sách, định tuyến và ngân sách; không phải solver runtime.</span></div><span class="controller-badge">BỘ ĐIỀU PHỐI</span></div>
    <div class="overview-facts">
      <div><dt>Chiến lược đã chọn</dt><dd>${UI_TEXT.labels.adaptiveAuto}</dd></div><div><dt>Chế độ đã chọn</dt><dd>${modeText(model.mode)}</dd></div><div><dt>Lý do dừng</dt><dd class="stop-value">${stopText(model.stopReason)}</dd></div>
      <div><dt>Lượt Agent thực thi</dt><dd>${agentCount}</dd></div><div><dt>Lượt gọi Model logic</dt><dd>${logical}</dd></div><div><dt>Request API thực tế</dt><dd>${physical}</dd></div>
    </div>
    <div class="overview-grid">
      <section class="overview-section"><h4>Phân tích cấu trúc</h4><div class="overview-field"><b>Khía cạnh (Aspects)</b>${displayList(aspectItems,"Chưa có evidence từ Analyzer")}</div><div class="overview-field"><b>Phụ thuộc (Dependencies)</b>${displayList(dependencyItems,"Không có")}</div><div class="overview-field"><b>Khả năng song song</b>${displayList(groupItems,"Chưa có nhóm song song")}</div></section>
      <section class="overview-section"><h4>Kiểm chứng và lựa chọn</h4><div class="overview-field"><b>Mức yêu cầu kiểm chứng</b><span class="evidence-value">${displayText(demandText(a.verification_demand),40)}</span></div><div class="overview-field"><b>Lý do</b>${displayList(reasons.map(phraseText),"Không có")}</div><div class="overview-field"><b>Vai trò / số lượng đã chọn</b>${displayList(roles,"Chưa có evidence lựa chọn")}</div><div class="overview-field"><b>Phán định</b>${displayList(verdicts,"Chưa có evidence từ Verifier")}</div></section>
    </div>
    <section class="overview-section overview-rationale"><h4>Lý giải của Agent phân tích</h4><p>${a.rationale?displayText(phraseText(a.rationale),900):"Chưa ghi nhận lý giải từ Agent phân tích."}</p></section>`
}
function renderAgents(model){
  const list=$("#agentList"),count=$("#agentCount");if(!list)return;count.textContent=String(model.agents.length);
  const openIds=new Set([...list.querySelectorAll("details[data-agent-id][open]")].map(item=>item.dataset.agentId));
  if(!model.agents.length){list.innerHTML='<div class="panel-empty">Chưa có lượt Agent thực thi.</div>';return}
  list.innerHTML=model.agents.map((agent,index)=>{const duration=agent.durationMs==null?"—":fmtLatency(agent.durationMs),tokenText=agent.totalTokens==null?"—":Number(agent.totalTokens).toLocaleString(),requests=agent.requests||0,issue=agent.escalationIssue||"";return `<details class="agent-card ${agent.status||"running"} ${agent.targetedRepair?"targeted-repair":""}" data-agent-id="${esc(agent.id)}"><summary><div class="agent-summary-main"><span>Lượt Agent thực thi #${index+1}</span><b>${displayText(roleText(agent.role),120)}</b></div><div class="agent-summary-side"><code>${displayText(agent.id,40)}</code><em>${statusText(agent.status)}</em></div></summary><div class="agent-card-body"><div class="agent-identity"><b>${displayText(roleText(agent.agentType),80)}</b><span>Vai trò runtime có giới hạn</span></div><div class="agent-facts"><div><dt>Mã lượt thực thi</dt><dd><code>${displayText(agent.id,60)}</code></dd></div><div><dt>Lượt gọi Model logic</dt><dd>#${agent.logicalCall??"—"}</dd></div><div><dt>Request API thực tế</dt><dd>${requests}${agent.attempts.length>1?` · lần thử ${agent.attempts.join(", ")}`:""}</dd></div><div><dt>Bắt đầu → kết thúc</dt><dd>${agent.startMs==null?"—":`+${agent.startMs} ms`} → ${agent.endMs==null?"—":`+${agent.endMs} ms`}</dd></div><div><dt>Thời lượng</dt><dd>${duration}</dd></div><div><dt>Nhà cung cấp / Mô hình</dt><dd>${displayText(providerText(agent.provider),70)} · ${displayText(agent.model,100)}</dd></div><div><dt>Token sử dụng</dt><dd>${tokenText}${agent.inputTokens!=null||agent.outputTokens!=null?` <small>(vào ${agent.inputTokens??"—"} · ra ${agent.outputTokens??"—"})</small>`:""}</dd></div><div><dt>Trạng thái</dt><dd>${statusText(agent.status)}</dd></div></div><div class="agent-goal"><b>Mục tiêu được giao</b><p>${displayText(phraseText(agent.assignedGoal),700)||"—"}</p></div><div class="agent-deps"><b>Phụ thuộc</b>${displayList(agent.dependencies,"Không có","agent-chips")}</div>${agent.targetedRepair?`<div class="agent-escalation"><b>Bổ sung xử lý có mục tiêu</b><p>${displayText(phraseText(issue)||"Được kích hoạt bởi vấn đề Verifier còn thiếu.",500)}</p></div>`:""}<div class="agent-output"><b>Bản xem trước đầu ra</b><p>${displayText(agent.outputPreview,520)||"Chưa ghi nhận đầu ra."}</p></div></div></details>`}).join("");
  list.querySelectorAll("details[data-agent-id]").forEach(item=>{if(openIds.has(item.dataset.agentId))item.open=true})
}
function graphType(agent){const type=(agent.agentType||agent.role||"").toLowerCase();if(type.includes("analyzer"))return "analyzer";if(type.includes("planner"))return "planner";if(type.includes("worker"))return "worker";if(type.includes("synth"))return "synth";if(type.includes("verifier"))return "verifier";if(type.includes("solver"))return "solver";return "agent"}
function buildGraph(model){
  const nodes=[{id:"controller",label:UI_TEXT.labels.adaptiveOrchestrator,type:"controller",status:"controller"}],edges=[],nodeIds=new Set(["controller"]),addNode=node=>{if(!nodeIds.has(node.id)){nodes.push(node);nodeIds.add(node.id)}},addEdge=(from,to,label="")=>{if(from&&to&&from!==to&&nodeIds.has(from)&&nodeIds.has(to)&&!edges.some(edge=>edge.from===from&&edge.to===to))edges.push({from,to,label})};
  model.agents.forEach(agent=>addNode({id:agent.id,label:roleText(agent.role),type:graphType(agent),status:agent.status,subtaskId:agent.subtaskId,batch:agent.batch,parallelBatch:agent.parallelBatch,targetedRepair:agent.targetedRepair}));
  if(!model.agents.length)return {nodes:[],edges:[]};
  const findType=type=>model.agents.filter(agent=>graphType(agent)===type),analyzers=findType("analyzer"),planners=findType("planner"),workers=findType("worker"),synths=findType("synth"),verifiers=findType("verifier"),solvers=findType("solver"),primaryWorkers=workers.filter(agent=>!agent.targetedRepair),repairWorkers=workers.filter(agent=>agent.targetedRepair),bySubtask=new Map(workers.filter(agent=>agent.subtaskId).map(agent=>[String(agent.subtaskId),agent]));
  const analyzer=analyzers[0],planner=planners[0],direct=solvers[0],primarySynth=synths[0],repairSynth=synths[1],firstVerifier=verifiers[0];if(analyzer)addEdge("controller",analyzer.id);else addEdge("controller",model.agents[0].id);
  if(planner){if(analyzer)addEdge(analyzer.id,planner.id);for(const worker of primaryWorkers){const deps=(worker.dependencies||[]).map(String).filter(item=>bySubtask.has(item));if(deps.length)deps.forEach(dep=>addEdge(bySubtask.get(dep).id,worker.id));else addEdge(planner.id,worker.id)}}
  else if(primaryWorkers){for(const worker of primaryWorkers){const deps=(worker.dependencies||[]).map(String).filter(item=>bySubtask.has(item));if(deps.length)deps.forEach(dep=>addEdge(bySubtask.get(dep).id,worker.id));else if(analyzer)addEdge(analyzer.id,worker.id)}}
  if(direct&&analyzer)addEdge(analyzer.id,direct.id);
  if(primarySynth){if(primaryWorkers.length)primaryWorkers.forEach(worker=>addEdge(worker.id,primarySynth.id));else if(direct)addEdge(direct.id,primarySynth.id);else if(analyzer)addEdge(analyzer.id,primarySynth.id)}
  if(firstVerifier){const source=primarySynth||direct||primaryWorkers.at(-1)||analyzer;if(source)addEdge(source.id,firstVerifier.id)}
  if(repairWorkers.length){if(firstVerifier)repairWorkers.forEach(worker=>addEdge(firstVerifier.id,worker.id));if(repairSynth){repairWorkers.forEach(worker=>addEdge(worker.id,repairSynth.id));if(verifiers[1])addEdge(repairSynth.id,verifiers[1].id)}else if(verifiers[1])repairWorkers.forEach(worker=>addEdge(worker.id,verifiers[1].id))}
  for(let index=1;index<verifiers.length;index+=1){if(!edges.some(edge=>edge.to===verifiers[index].id))addEdge(verifiers[index-1].id,verifiers[index].id)}
  const finalAgent=verifiers.at(-1)||synths.at(-1)||workers.at(-1)||direct||planner||analyzer;addNode({id:"stop",label:stopText(model.stopReason||"STOP"),type:"stop",status:model.status,stopReason:model.stopReason});if(finalAgent)addEdge(finalAgent.id,"stop");
  return {nodes,edges}
}
function focusGraphAgent(id){if(!id||id==="controller"||id==="stop")return;switchInspectorTab("agents");const card=$(`#agentList details[data-agent-id="${id}"]`);if(card){card.open=true;card.scrollIntoView({block:"nearest"})}}
function renderGraph(model){
  const box=$("#executionGraph"),mode=$("#graphMode");if(!box)return;mode.textContent=modeText(model.mode);const graph=buildGraph(model);if(!graph.nodes.length){box.innerHTML='<div class="panel-empty">Chưa có bằng chứng sơ đồ.</div>';return}
  const incoming=new Map(graph.nodes.map(node=>[node.id,[]]));graph.edges.forEach(edge=>incoming.get(edge.to)?.push(edge.from));const rank=new Map([["controller",0]]);for(let pass=0;pass<graph.nodes.length+2;pass+=1){let changed=false;for(const node of graph.nodes){const parents=incoming.get(node.id)||[];if(parents.length){const value=Math.max(...parents.map(parent=>rank.get(parent)??0))+1;if(value!==(rank.get(node.id)??-1)){rank.set(node.id,value);changed=true}}}if(!changed)break}
  graph.nodes.forEach(node=>{if(!rank.has(node.id))rank.set(node.id,0)});const groups=new Map();graph.nodes.forEach(node=>{const key=rank.get(node.id);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(node)});const nodeWidth=158,nodeHeight=58,gap=18,pad=20,rowGap=92,maxGroup=Math.max(...[...groups.values()].map(group=>group.length)),width=Math.max(332,pad*2+maxGroup*nodeWidth+(maxGroup-1)*gap),height=Math.max(218,pad*2+groups.size*rowGap+nodeHeight);const positions=new Map();[...groups.entries()].sort((a,b)=>a[0]-b[0]).forEach(([row,group])=>{const rowWidth=group.length*nodeWidth+(group.length-1)*gap,start=(width-rowWidth)/2;group.forEach((node,index)=>positions.set(node.id,{x:start+index*(nodeWidth+gap),y:pad+row*rowGap}))});
  const edgeSvg=graph.edges.map(edge=>{const from=positions.get(edge.from),to=positions.get(edge.to);if(!from||!to)return"";return `<path class="graph-edge" d="M ${from.x+nodeWidth/2} ${from.y+nodeHeight} C ${from.x+nodeWidth/2} ${from.y+nodeHeight+22}, ${to.x+nodeWidth/2} ${to.y-22}, ${to.x+nodeWidth/2} ${to.y}" marker-end="url(#graphArrow)"></path>`}).join("");
  const nodeSvg=graph.nodes.map(node=>{const position=positions.get(node.id),second=node.type==="controller"?"Bộ điều phối · chính sách/định tuyến":node.type==="stop"?stopText(node.stopReason||node.status):(node.parallelBatch?`Nhóm song song #${node.batch}`:node.subtaskId||statusText(node.status)||"runtime");return `<g class="graph-node graph-${node.type} ${node.targetedRepair?"graph-targeted":""}" data-agent-id="${esc(node.id)}" role="button" tabindex="0" aria-label="${displayText(node.label,120)}"><rect x="${position.x}" y="${position.y}" width="${nodeWidth}" height="${nodeHeight}" rx="10"></rect><text x="${position.x+nodeWidth/2}" y="${position.y+23}" text-anchor="middle">${displayText(node.label,28)}</text><text class="graph-node-sub" x="${position.x+nodeWidth/2}" y="${position.y+42}" text-anchor="middle">${displayText(second,30)}</text></g>`}).join("");
  const batchNotes=model.batches.filter(batch=>batch.parallel).map(batch=>`Ready-set: ${(batch.nodes||[]).join(" + ")} chạy đồng thời`).join(" · ");box.innerHTML=`<div class="graph-legend"><span><i class="legend-dot controller"></i>Bộ điều phối</span><span><i class="legend-dot runtime"></i>Lượt Agent thực thi</span><span><i class="legend-dot parallel"></i>Nhóm chạy song song</span></div><svg class="graph-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="DAG runtime của lượt chạy"><defs><marker id="graphArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor"></path></marker></defs>${edgeSvg}${nodeSvg}</svg>${batchNotes?`<div class="graph-batches"><b>Bộ lập lịch ready-set</b><span>${displayText(batchNotes,700)}</span></div>`:""}`;requestAnimationFrame(()=>{box.scrollLeft=Math.max(0,(box.scrollWidth-box.clientWidth)/2)});
  box.querySelectorAll(".graph-node[data-agent-id]").forEach(node=>{node.addEventListener("click",()=>focusGraphAgent(node.dataset.agentId));node.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();focusGraphAgent(node.dataset.agentId)}})})
}
function quickStatusClass(status){return status==="failed"?"failed":status==="degraded"?"warning":status==="completed"||status==="stopped"?"done":"idle"}
function quickStepDescription(agent){if(agent.targetedRepair)return agent.escalationIssue?`Bổ sung đúng vấn đề: ${phraseText(agent.escalationIssue)}`:"Bổ sung có mục tiêu theo kết quả kiểm tra.";const type=graphType(agent);return ({analyzer:"Phân tích cấu trúc, phụ thuộc, khả năng song song và nhu cầu kiểm chứng.",planner:"Lập kế hoạch và DAG thực thi theo các phụ thuộc đã phát hiện.",solver:"Xử lý trực tiếp yêu cầu trong phạm vi context được cung cấp.",synth:"Tổng hợp đầu ra của các Agent thành một câu trả lời thống nhất.",verifier:"Kiểm tra mức đầy đủ, mâu thuẫn và yêu cầu bổ sung có mục tiêu."}[type]||phraseText(agent.assignedGoal||fallbackGoal(agent.agentType)))}
function renderQuickDetails(model){
  const run=model.run||{},metrics=model.metrics||{},hasRun=Boolean(run.run_id),status=hasRun?statusText(model.status):"Chưa chạy",statusBox=$("#quickStatus");
  if(statusBox){statusBox.className=`quick-status ${quickStatusClass(model.status)}`;statusBox.innerHTML=`<span class="quick-dot"></span><span>${esc(status)}</span>`}
  $("#quickLatency").textContent=metrics.e2e_ms==null?"—":fmtLatency(metrics.e2e_ms);$("#quickCost").textContent=metrics.calculated_cost_usd==null?"—":`$${Number(metrics.calculated_cost_usd).toFixed(6)}`;
  const reason=model.why?phraseText(model.why):model.analysis?.rationale?phraseText(model.analysis.rationale):"Quyết định dựa trên tín hiệu cấu trúc của task và ngân sách runtime.";
  $("#quickSummary").innerHTML=hasRun?`Adaptive Agent chọn <b>${esc(modeText(model.mode))}</b>. ${esc(String(reason).slice(0,420))}`:"Chọn một lượt chạy để xem cách Adaptive Agent đã xử lý yêu cầu.";
  const timeline=$("#quickTimeline");timeline.innerHTML=model.agents.length?model.agents.map(agent=>`<div class="quick-step ${agent.status==="failed"?"failed":""}"><div class="quick-step-time">${agent.durationMs==null?"—":fmtLatency(agent.durationMs)}</div><div class="quick-step-body"><b>${displayText(roleText(agent.role),90)}</b><span>${displayText(quickStepDescription(agent),240)}</span></div></div>`).join(""):'<div class="quick-empty">Chưa có bước thực thi.</div>';
  const retrieval=run.retrieval_meta||{},chunks=Array.isArray(retrieval.selected_chunks)?retrieval.selected_chunks:[],attached=Array.isArray(retrieval.attached_sources)?retrieval.attached_sources:[],docs=(attached.length?attached.map(source=>typeof source==="string"?source:source?.filename).filter(Boolean):Array.isArray(retrieval.source_document_ids)?retrieval.source_document_ids:[]),$sources=$("#quickSources");
  $sources.innerHTML=docs.length?`${docs.map(doc=>`<div class="quick-source">${svgIcon("file","small")}<span>${displayText(doc,120)}</span></div>`).join("")}<small>${chunks.length||retrieval.chunks_selected||0} đoạn context</small>`:'<span class="quick-empty">Không có nguồn hoặc tài liệu bổ sung.</span>';
  $("#quickRaw").textContent=JSON.stringify(safeFrontendEvidence(run.run_id?run:{}),null,2);$("#quickRerun").disabled=!hasRun||busy;$("#openEvidence").disabled=!hasRun;
  $("#evStatus").textContent=status;$("#evLatency").textContent=metrics.e2e_ms==null?"—":fmtLatency(metrics.e2e_ms);$("#evCost").textContent=metrics.calculated_cost_usd==null?"—":`$${Number(metrics.calculated_cost_usd).toFixed(6)}`;$("#evAgents").textContent=String(model.agents.length);$("#evSources").textContent=`${docs.length} tệp · ${chunks.length||retrieval.chunks_selected||0} đoạn`;$("#evidenceModelSummary").textContent=[run.model,modeText(model.mode)].filter(Boolean).join(" · ")||"—";
}
function mountEvidenceWorkspace(){const mount=$("#evidenceMount"),tabs=$("#inspector .inspector-tabs"),body=$("#inspector .inspector-body"),context=$("#contextProvenance"),contextMount=$("#evidenceContextMount");if(mount&&tabs&&body){mount.append(tabs,body)}if(context&&contextMount)contextMount.append(context)}
function openContextScreen(id){const screen=$(`#${id}`);if(!screen)return;contextReturnFocus=document.activeElement;$$('.context-screen').forEach(item=>{const active=item===screen;item.classList.toggle("open",active);item.setAttribute("aria-hidden",String(!active))});if(id==="executionEvidence")switchInspectorTab(localStorage.getItem(INSPECTOR_TAB_KEY)==="context"?"context":"graph");screen.querySelector(".context-back")?.focus()}
function closeContextScreens(){$$('.context-screen').forEach(item=>{item.classList.remove("open");item.setAttribute("aria-hidden","true")});contextReturnFocus?.focus?.();contextReturnFocus=null}
function rerunSelectedQuestion(){if(busy)return;const selected=$(".turn-card.selected-run")||$$('.turn-card').at(-1),question=selected?.querySelector(".question-text")?.textContent?.trim();if(!question){toast("Không tìm thấy câu hỏi để chạy lại.","error");return}closeInspector();promptEl.value=question;autoSize();runChat()}
function renderEvidencePanels(){const model=evidenceModel();renderOverview(model);renderAgents(model);renderGraph(model);renderQuickDetails(model)}

async function runChat(){
  const text=promptEl.value.trim();if(!text||busy)return;if(contextAttachmentPending()){setContextOpen(true);toast("Hãy đợi tệp xử lý xong trước khi gửi.","error");return}if($("#context").value.length>100000){setContextOpen(true);toast("Ngữ cảnh vượt giới hạn 100.000 ký tự.","error");return}const provider=$("#provider").value,model=selectedModel(),mode=selectedMode(),status=selectionStatus();if(provider!=="fake"&&status==="missing"){toast(`${providerText(provider)} chưa có khóa API. Chọn provider khác hoặc cấu hình .env.`,"error");return}
  currentRequestedMode=mode;busy=true;sendBtn.disabled=true;currentRunId=null;$("#exportBtn").disabled=true;liveTurn=makeTurnCard(text,{pending:true});history.push({role:"user",content:text});promptEl.value="";autoSize();resetInspector();currentRequestedMode=mode;currentRunEvidence={strategy:"adaptive",provider,model,processing_mode:mode,events:rawEvents,status:"running",stop_reason:""};$("#insStrategy").textContent=mode==="adaptive-auto"?UI_TEXT.labels.adaptiveAuto:modeText(mode);$("#insProvider").textContent=providerText(provider);renderEvidencePanels();
  try{
    const response=await fetch("/api/chat/stream",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text,context:$("#context").value,context_sources:contextSourcesForRequest(),provider,model,mode,conversation_id:currentConversationId,history:history.slice(0,-1)})});if(!response.ok)throw new Error(await response.text());if(!response.body)throw new Error("Server không trả về stream");
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="",final=null,fatal=null;const consume=line=>{if(!line.trim())return;let event;try{event=JSON.parse(line)}catch{throw new Error("Stream trả về dữ liệu không hợp lệ")};if(event.type==="trace")traceEvent(event.event);if(event.type==="metrics")renderMetrics(event.metrics);if(event.type==="final"){final=event;renderMetrics(event.metrics)}if(event.type==="fatal")fatal=event};
    while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const parts=buffer.split("\n");buffer=parts.pop();for(const line of parts)consume(line)}buffer+=decoder.decode();consume(buffer);
    if(!final&&fatal){currentConversationId=fatal.conversation_id||currentConversationId;rememberConversation(currentConversationId);currentRunId=fatal.run_id||null;const error=new Error(fatal.error||"Provider error");error.persisted=true;error.fatal=fatal;throw error}if(!final)throw new Error("Run kết thúc mà không có final event");
    currentConversationId=final.conversation_id||currentConversationId;rememberConversation(currentConversationId);currentRunId=final.run_id||null;$("#exportBtn").disabled=!currentRunId;const answer=final.answer?.trim()||(final.status==="failed"?friendlyRunError(final.error,final.provider||provider,final.model||model):"Lượt chạy kết thúc nhưng chưa tạo được câu trả lời.");const completedMode=mapUiModeToChatStrategy(final.processing_mode||mode)||mode;currentRunEvidence={...(currentRunEvidence||{}),run_id:currentRunId,strategy:"adaptive",provider:final.provider||provider,model:final.model||model,processing_mode:completedMode,status:final.status,stop_reason:final.stop_reason,sources:final.sources||[],events:rawEvents,metrics:final.metrics||currentMetrics};setTurnAnswer(liveTurn,answer,{runId:currentRunId,provider:final.provider,model:final.model,status:final.status,stopReason:final.stop_reason,mode:currentMode||completedMode,requestedMode:completedMode,metrics:final.metrics,sources:final.sources||[]});history.push({role:"assistant",content:answer,sources:final.sources||[]});$("#chatTitle").textContent=history.find(x=>x.role==="user")?.content.slice(0,54)||"Adaptive Agent";$("#runState").textContent=stopText(final.stop_reason||final.status||"completed");$("#runState").className="run-state "+(final.status==="failed"?"error":final.status==="degraded"?"warning":"done");renderEvidencePanels();if(final.status==="failed")toast("Không thể hoàn thành lượt chạy.","error");await loadConversations()
  }catch(error){
    if(!error.persisted&&history.at(-1)?.role==="user"&&history.at(-1)?.content===text)history.pop();const fatal=error.fatal||{};const answer=friendlyRunError(error.message,fatal.provider||provider,fatal.model||model);currentRunEvidence={...(currentRunEvidence||{}),run_id:fatal.run_id||currentRunId,provider:fatal.provider||provider,model:fatal.model||model,processing_mode:mapUiModeToChatStrategy(fatal.processing_mode||mode)||mode,status:"failed",stop_reason:fatal.stop_reason||"STOP_FAILURE",events:rawEvents,metrics:{}};setTurnAnswer(liveTurn,answer,{runId:fatal.run_id,provider:fatal.provider||provider,model:fatal.model||model,status:"failed",stopReason:fatal.stop_reason||"STOP_FAILURE",mode:currentMode||mode,requestedMode:mode,metrics:{}});$("#runState").textContent=stopText(fatal.stop_reason||"STOP_FAILURE");$("#runState").className="run-state error";renderEvidencePanels();toast("Không thể hoàn thành lượt chạy.","error");if(error.persisted)await loadConversations()
  }finally{busy=false;sendBtn.disabled=false;liveTurn=null;promptEl.focus();scrollBottom()}
}

async function testProvider(){
  const provider=$("#provider").value,model=selectedModel(),check=$("#providerCheck");if(provider==="fake"){toast("Fake hoạt động ngoại tuyến.","success");return}check.textContent="…";check.setAttribute("aria-busy","true");
  try{const response=await fetch("/api/provider/test",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider,model})});const data=await response.json();if(!response.ok)throw new Error(data.detail||data.error||"Lỗi API");const ok=data.error_category==="SUCCESS",status=ok?"ready":data.error_category==="NOT_CONFIGURED"?"missing":"failed";cfg.provider_status[provider]={status,model,error_category:data.error_category,safe_message:data.safe_message};updateProviderDisplay();toast(ok?`${providerText(provider)} hoạt động · ${model}`:`${providerText(provider)} · ${data.error_category}: ${data.safe_message}`,ok?"success":"error")}
  catch(error){cfg.provider_status[provider]={status:"failed",model,error_category:"PROVIDER_ERROR",safe_message:error.message};updateProviderDisplay();toast(`${providerText(provider)} · ${model}: ${error.message}`,"error")}
  finally{check.textContent="●";check.removeAttribute("aria-busy")}
}

async function loadConversations(openLatest=false){
  try{const response=await fetch("/api/conversations?limit=60");if(!response.ok)throw new Error(`History error (${response.status})`);const data=await response.json(),box=$("#threads");conversationCache=data.conversations||[];box.innerHTML="";if(!conversationCache.length){box.innerHTML='<div class="history-empty">Chưa có cuộc trò chuyện.</div>';renderSearchResults($("#searchInput")?.value||"");return}
    conversationCache.forEach(c=>{const active=c.conversation_id===currentConversationId,card=document.createElement("div");card.className="thread-card"+(active?" active":"");card.dataset.id=c.conversation_id;card.innerHTML=`<button class="thread-main"><span class="sidebar-icon">${svgIcon("chat","small")}</span><span class="thread-title">${esc(c.title)}</span></button><div class="thread-actions"><details class="thread-menu"><summary title="Tùy chọn" aria-label="Tùy chọn cuộc trò chuyện ${esc(c.title||"")}"><span class="sidebar-icon conv-more"><svg class="ui-icon small"><use href="#ui-more"></use></svg></span></summary><div class="thread-menu-popover"><button class="rename">Đổi tên</button><button class="delete">Xóa</button></div></details></div>`;const main=card.querySelector(".thread-main"),rename=card.querySelector(".rename"),remove=card.querySelector(".delete"),menu=card.querySelector(".thread-menu"),popover=card.querySelector(".thread-menu-popover"),summary=card.querySelector("summary");const turnCount=c.turn_count||c.run_count||0,preview=c.last_preview||"Chưa có nội dung",time=fmtTime(c.updated_at);main.setAttribute("aria-label",`Mở cuộc trò chuyện ${c.title||""}`);main.title=`${preview}\n${turnCount} lượt${time?` · ${time}`:""}`;rename.setAttribute("aria-label",`Đổi tên cuộc trò chuyện ${c.title||""}`);remove.setAttribute("aria-label",`Xóa cuộc trò chuyện ${c.title||""}`);main.onclick=()=>loadConversation(c.conversation_id);menu.addEventListener("toggle",()=>{if(!menu.open)return;closeConversationMenus(menu);requestAnimationFrame(()=>{const rect=summary.getBoundingClientRect(),width=popover.offsetWidth,height=popover.offsetHeight;popover.style.left=Math.max(8,Math.min(innerWidth-width-8,rect.right-width))+"px";const below=rect.bottom+4,top=below+height<=innerHeight-8?below:Math.max(8,rect.top-height-4);popover.style.top=top+"px"})});rename.onclick=e=>{e.stopPropagation();menu.open=false;renameConversation(c)};remove.onclick=e=>{e.stopPropagation();menu.open=false;deleteConversation(c)};box.appendChild(card)});renderSearchResults($("#searchInput")?.value||"");
    if(openLatest&&!currentConversationId){const remembered=localStorage.getItem(ACTIVE_CONVERSATION_KEY);const candidate=conversationCache.find(x=>x.conversation_id===remembered)||conversationCache[0];await loadConversation(candidate.conversation_id)}
  }catch(error){toast("Không tải được lịch sử: "+error.message,"error")}
}
function renderSearchResults(query=""){
  const box=$("#searchResults");if(!box)return;const needle=query.trim().toLocaleLowerCase("vi-VN"),items=conversationCache.filter(item=>!needle||`${item.title||""} ${item.last_preview||""}`.toLocaleLowerCase("vi-VN").includes(needle));
  box.innerHTML="";if(!items.length){box.innerHTML='<div class="empty-search">Không tìm thấy cuộc trò chuyện</div>';return}items.forEach(item=>{const row=document.createElement("button"),title=String(item.title||"Cuộc trò chuyện"),preview=String(item.last_preview||"").trim(),secondary=preview&&preview!==title?`<small>${esc(preview)}</small>`:"";row.className="search-result";row.type="button";row.setAttribute("role","option");row.innerHTML=`<span class="sidebar-icon search-result-icon">${svgIcon("chat","small")}</span><span class="search-result-copy"><b>${esc(title)}</b>${secondary}</span>`;row.onclick=()=>{closeFloatingUi();loadConversation(item.conversation_id)};box.appendChild(row)})
}
function renameConversation(c){pendingRenameConversation=c;const dialog=$("#renameDialog"),input=$("#renameInput");input.value=c.title||"";dialog.classList.add("open");dialog.setAttribute("aria-hidden","false");requestAnimationFrame(()=>{input.focus();input.select()})}
async function confirmRenameConversation(){const c=pendingRenameConversation,title=$("#renameInput").value.trim();if(!c||!title)return;try{const r=await fetch(`/api/conversations/${encodeURIComponent(c.conversation_id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({title})});if(!r.ok)throw new Error(await r.text());if(currentConversationId===c.conversation_id)$("#chatTitle").textContent=title;closeRenameDialog();await loadConversations();toast("Đã đổi tên","success")}catch(e){toast("Không đổi tên được: "+e.message,"error")}}
function closeRenameDialog(){const dialog=$("#renameDialog");dialog.classList.remove("open");dialog.setAttribute("aria-hidden","true");pendingRenameConversation=null}
function deleteConversation(c){pendingDeleteConversation=c;const dialog=$("#deleteConfirm");dialog.classList.add("open");dialog.setAttribute("aria-hidden","false");$("#confirmDelete").focus()}
async function confirmDeleteConversation(){const c=pendingDeleteConversation;if(!c)return;try{const r=await fetch(`/api/conversations/${encodeURIComponent(c.conversation_id)}`,{method:"DELETE"});if(!r.ok)throw new Error(await r.text());if(currentConversationId===c.conversation_id)newConversation();pendingDeleteConversation=null;closeDeleteConfirm();await loadConversations(!currentConversationId);toast("Đã xóa cuộc trò chuyện","success")}catch(e){toast("Không xóa được: "+e.message,"error")}}
function closeDeleteConfirm(){const dialog=$("#deleteConfirm");dialog.classList.remove("open");dialog.setAttribute("aria-hidden","true");pendingDeleteConversation=null}
async function loadConversation(id){
  if(busy)return;try{const response=await fetch(`/api/conversations/${encodeURIComponent(id)}`);if(!response.ok)throw new Error("not found");const conversation=await response.json();clearContextFile();currentConversationId=id;rememberConversation(id);app.classList.remove("mobile-side-open");updatePanelButtons();history=(conversation.messages||[]).map(m=>({role:m.role,content:m.content}));messages.innerHTML="";const turns=conversation.turns||fallbackTurns(conversation.messages);for(const turn of turns)renderTurn(turn,conversation);$("#chatTitle").textContent=conversation.title||"Cuộc trò chuyện";if(typeof conversation.context==="string")$("#context").value=conversation.context;persistedContextSources=Array.isArray(conversation.context_sources)?conversation.context_sources:[];renderContextAttachments();if(conversation.provider&&cfg.available[conversation.provider]){$("#provider").value=conversation.provider;populateModels(conversation.model)}if(conversation.processing_mode){const restored=mapUiModeToChatStrategy(conversation.processing_mode)||"adaptive-auto";localStorage.setItem("adaptive.mode",restored);currentRequestedMode=restored;updateModeDisplay();renderModelPicker()}currentRunId=(conversation.run_ids||[]).at(-1)||null;$("#exportBtn").disabled=!currentRunId;await loadConversations();if(currentRunId)await loadRunInspector(currentRunId);else resetInspector("idle");scrollBottom()
  }catch(error){if(currentConversationId===id){currentConversationId=null;rememberConversation(null)}toast("Không đọc được cuộc trò chuyện: "+error.message,"error")}
}
async function loadRunInspector(id){
  try{const response=await fetch(`/api/runs/${encodeURIComponent(id)}`);if(!response.ok)throw new Error("not found");const run=await response.json();currentRunId=id;$("#exportBtn").disabled=false;rawEvents=run.events||[];currentRunEvidence={...run,events:rawEvents};currentMetrics=run.metrics||{};currentRequestedMode=mapUiModeToChatStrategy(run.processing_mode)||"adaptive-auto";updateModeDisplay();trace.innerHTML="";$("#rawEvents").textContent=JSON.stringify(safeFrontendEvidence(run),null,2);currentMode=null;renderSnapshot(run.retrieval_meta);rawEvents.forEach(appendTrace);renderMetrics(run.metrics);$("#insStrategy").textContent=run.strategy==="adaptive"?(run.processing_mode&&run.processing_mode!=="adaptive-auto"?modeText(run.processing_mode):UI_TEXT.labels.adaptiveAuto):strategyText(run.strategy);$("#insProvider").textContent=providerText(run.provider);$("#runState").textContent=stopText(run.stop_reason||run.status);$("#runState").className="run-state "+(run.status==="failed"?"error":run.status==="degraded"?"warning":"done");renderEvidencePanels();$$('.turn-card').forEach(card=>card.classList.toggle('selected-run',card.dataset.runId===id))
  }catch(error){toast("Không đọc được run evidence","error")}
}
async function downloadRun(id){try{const response=await fetch(`/api/runs/${encodeURIComponent(id)}`,{method:"HEAD"});if(!response.ok&&response.status!==405)throw new Error("not found");const a=document.createElement("a");a.href=`/api/runs/${encodeURIComponent(id)}`;a.download=`${id}.json`;document.body.appendChild(a);a.click();a.remove()}catch{toast("Không export được evidence","error")}}

function compareResult(key){return compareResults.get(key)||null}
function compareValue(value,formatter=value=>String(value)){return value==null?"—":formatter(value)}
function compareAnswer(result,limit=250){if(!result)return"Chưa chạy";if(result.answer)return String(result.answer).replace(/\s+/g," ").trim().slice(0,limit);return result.error?`Không có câu trả lời · ${String(result.error).slice(0,120)}`:"Không có câu trả lời"}
function renderComparisonSurfaces(){
  const fixed=compareResult("fixed"),adaptive=compareResult("adaptive"),fill=(id,value)=>{const node=$(`#${id}`);if(node)node.textContent=value};
  fill("quickFixedAnswer",compareAnswer(fixed));fill("quickAdaptiveAnswer",compareAnswer(adaptive));fill("quickFixedLatency",compareValue(fixed?.metrics?.e2e_ms,fmtLatency));fill("quickAdaptiveLatency",compareValue(adaptive?.metrics?.e2e_ms,fmtLatency));fill("quickFixedCost",compareValue(fixed?.metrics?.calculated_cost_usd,value=>`$${Number(value).toFixed(6)}`));fill("quickAdaptiveCost",compareValue(adaptive?.metrics?.calculated_cost_usd,value=>`$${Number(value).toFixed(6)}`));fill("quickFixedStatus",fixed?statusText(fixed.status):"Chưa chạy");fill("quickAdaptiveStatus",adaptive?statusText(adaptive.status):"Chưa chạy");
  const order=["single","fixed","static","adaptive"],results=order.map(compareResult),rows=[
    ["Model",result=>result?.model||"—"],["Cách xử lý",result=>result?strategyText(result.strategy):"—"],["Trạng thái",result=>result?statusText(result.status):"—"],["Lý do dừng",result=>result?stopText(result.stop_reason):"—"],["Agent Executions",result=>compareValue(result?.metrics?.agent_executions)],["Logical Calls",result=>compareValue(result?.metrics?.logical_calls)],["Physical Requests",result=>compareValue(result?.metrics?.physical_requests)],["Input Tokens",result=>compareValue(result?.metrics?.input_tokens,value=>Number(value).toLocaleString())],["Output Tokens",result=>compareValue(result?.metrics?.output_tokens,value=>Number(value).toLocaleString())],["Total Tokens",result=>compareValue(result?.metrics?.total_tokens,value=>Number(value).toLocaleString())],["E2E Latency",result=>compareValue(result?.metrics?.e2e_ms,fmtLatency)],["Calculated Cost",result=>compareValue(result?.metrics?.calculated_cost_usd,value=>`$${Number(value).toFixed(6)}`)],["Chất lượng",()=>UI_TEXT.labels.notEvaluated],["Evidence",result=>result?.run_id?`<button class="report-evidence" data-run-id="${esc(result.run_id)}">Mở</button>`:"—"]
  ];
  const body=$("#comparisonMatrixBody");if(body)body.innerHTML=rows.map(([label,getter])=>`<tr><td>${esc(label)}</td>${results.map(result=>`<td>${label==="Evidence"?getter(result):esc(String(getter(result)))}</td>`).join("")}</tr>`).join("");
  const answers=$("#comparisonAnswers");if(answers)answers.innerHTML=order.map((strategy,index)=>{const result=results[index];return `<article class="report-answer"><h3>${strategyText(strategy)}</h3><div class="strategy-sub">${result?statusText(result.status):"Chưa chạy"}</div><p>${esc(compareAnswer(result,520))}</p></article>`}).join("");
  $$('.report-evidence').forEach(button=>button.onclick=async()=>{await loadRunInspector(button.dataset.runId);closeContextScreens();openContextScreen("executionEvidence")});
  const ready=compareResults.size===4;$("#openComparisonReport").disabled=!ready;$("#comparisonModelSummary").textContent=ready?`4 strategy · snapshot ${compareSnapshotId||"—"} · chạy tuần tự`:"Chưa có kết quả so sánh đầy đủ";
}

function openCompare(){if(!promptEl.value.trim()&&!history.length){toast("Nhập task hoặc mở một cuộc trò chuyện trước.");return}modalReturnFocus=document.activeElement;$("#advancedMenu").open=false;closeInspector();const modal=$("#compareModal");modal.classList.add("open");modal.setAttribute("aria-hidden","false");$("#closeCompare").focus()}
function closeCompare(){const modal=$("#compareModal");modal.classList.remove("open");modal.setAttribute("aria-hidden","true");if(modalReturnFocus?.focus)modalReturnFocus.focus();modalReturnFocus=null}
async function runCompare(){
  if(compareBusy)return;let message=promptEl.value.trim();if(!message&&history.length)message=[...history].reverse().find(x=>x.role==="user")?.content||"";if(!message){toast("Không tìm thấy task.","error");return}const provider=$("#provider").value,model=selectedModel();if(provider!=="fake"&&!confirm("So sánh sẽ gọi đủ 4 strategy bằng API thật và tiêu usage. Bạn có muốn tiếp tục không?"))return;
  compareBusy=true;compareResults=new Map();compareSnapshotId=null;renderComparisonSurfaces();$("#runCompare").disabled=true;$("#openComparisonReport").disabled=true;$("#compareRows").innerHTML="";$("#compareProgress").textContent="Đang chạy tuần tự để latency không chồng lẫn nhau…";
  const unavailable=value=>value==null?unavailableText():String(value),metric=value=>value==null?unavailableText():Number(value).toLocaleString(),cost=value=>value==null?unavailableText():"$"+Number(value).toFixed(5);
  try{const response=await fetch("/api/compare/stream",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message,context:$("#context").value,context_sources:contextSourcesForRequest(),provider,model,history:[]})});if(!response.ok)throw new Error(await response.text());const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="";const consume=line=>{if(!line.trim())return;const event=JSON.parse(line);if(event.type==="compare_start")$("#compareProgress").textContent=`Đang chạy ${strategyText(event.strategy)} (${event.order||"—"}/4)…`;if(event.type==="compare_result"){const result=event.result||{},m=result.metrics||{};compareResults.set(String(result.strategy||"").toLowerCase(),result);renderComparisonSurfaces();const answer=result.answer?`<details class="compare-answer"><summary>${esc(String(result.answer).replace(/\s+/g," ").slice(0,140))}</summary><div>${markdown(result.answer)}</div></details>`:`<span class="compare-unavailable">${unavailableText()}</span>`;const error=result.error?`<small class="compare-error">${esc(result.error)}</small>`:"";const evidence=result.run_id?`<button class="compare-evidence" data-run-id="${esc(result.run_id)}">Xem</button>`:`<span class="compare-unavailable">${unavailableText()}</span>`;$("#compareRows").insertAdjacentHTML("beforeend",`<tr><td><b>${strategyText(result.strategy||"—")}</b></td><td class="compare-answer-cell">${answer}${error}</td><td>${statusText(result.status)}</td><td>${stopText(result.stop_reason)}</td><td>${metric(m.agent_executions)}</td><td>${metric(m.logical_calls)}</td><td>${metric(m.physical_requests)}</td><td>${metric(m.input_tokens)}</td><td>${metric(m.output_tokens)}</td><td>${metric(m.total_tokens)}</td><td>${m.e2e_ms==null?unavailableText():fmtLatency(m.e2e_ms)}</td><td>${cost(m.calculated_cost_usd)}</td><td>${UI_TEXT.labels.notEvaluated}</td><td>${evidence}</td></tr>`);const link=$("#compareRows tr:last-child .compare-evidence");if(link)link.onclick=async()=>{closeCompare();await loadRunInspector(result.run_id);openContextScreen("executionEvidence")}}if(event.type==="compare_final"){compareSnapshotId=event.snapshot_id||null;renderComparisonSurfaces();const id=event.snapshot_id?` · snapshot ${event.snapshot_id}`:"";$("#compareProgress").textContent=`Hoàn tất. Cả 4 strategy dùng cùng Ngữ cảnh đã đóng băng (Frozen Context) và chạy tuần tự${id}. Chất lượng: ${UI_TEXT.labels.notEvaluated}.`}};while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const parts=buffer.split("\n");buffer=parts.pop();parts.forEach(consume)}buffer+=decoder.decode();consume(buffer)}catch(error){$("#compareProgress").textContent="Lỗi: "+error.message}finally{compareBusy=false;$("#runCompare").disabled=false;renderComparisonSurfaces()}
}

function newConversation(){history=[];currentRunId=null;currentConversationId=null;rememberConversation(null);app.classList.remove("mobile-side-open");updatePanelButtons();$("#exportBtn").disabled=true;$("#chatTitle").textContent="Cuộc trò chuyện mới";$("#context").value="";clearContextFile();messages.innerHTML='<div class="welcome compact-welcome"><div class="welcome-mark">✦</div><h1>Tôi có thể giúp gì cho bạn?</h1><p>Cuộc trò chuyện chỉ được tạo sau khi bạn gửi tin nhắn đầu tiên.</p></div>';$$('.thread-card').forEach(x=>x.classList.remove('active'));resetInspector("idle");promptEl.focus()}
function setContextOpen(open,returnFocus=false){const drawer=$("#contextDrawer");drawer.classList.toggle("open",open);drawer.setAttribute("aria-hidden",String(!open));const trigger=$("#attachButton");trigger?.setAttribute("aria-expanded",String(open));if(open)requestAnimationFrame(()=>$("#context").focus());else if(returnFocus)trigger?.focus()}
function closeMobilePanels(){app.classList.remove("mobile-side-open","mobile-ins-open");persistPanels()}
function downloadCurrentEvidence(){if(currentRunId){downloadRun(currentRunId);return}const blob=new Blob([JSON.stringify(currentRunEvidence||{events:rawEvents},null,2)],{type:"application/json"}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="run-evidence.json";document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000)}

function closeFloatingUi(except=null){
  [$("#searchPopover"),$("#helpPopover"),$("#sharePopover"),$("#accountMenu"),$("#modelMenu")].forEach(node=>{if(!node||node===except)return;node.classList.remove("open");node.setAttribute("aria-hidden","true")});
  [["#searchChat","#searchPopover"],["#helpButton","#helpPopover"],["#shareButton","#sharePopover"],["#profile","#accountMenu"],["#modelMenuButton","#modelMenu"]].forEach(([button,panel])=>{if($(panel)!==except)$(button)?.setAttribute("aria-expanded","false")});
}
function closeConversationMenus(except=null){$$('.thread-menu[open]').forEach(menu=>{if(menu!==except)menu.open=false})}
function toggleAnchoredPopover(button,popover){const willOpen=!popover.classList.contains("open");closeFloatingUi(willOpen?popover:null);popover.classList.toggle("open",willOpen);popover.setAttribute("aria-hidden",String(!willOpen));button.setAttribute("aria-expanded",String(willOpen));if(willOpen){if(popover.id==="modelMenu"){renderModelPicker();requestAnimationFrame(()=>{positionModelMenu();popover.querySelector('.model-choice[aria-selected="true"]')?.focus()})}else{const rect=button.getBoundingClientRect();if(popover.id!=="searchPopover"&&popover.id!=="accountMenu"){popover.style.left=Math.max(8,Math.min(innerWidth-popover.offsetWidth-8,rect.left))+"px";popover.style.top=Math.min(innerHeight-popover.offsetHeight-8,rect.bottom+6)+"px"}}}return willOpen}
function openSettings(){modalReturnFocus=document.activeElement;closeFloatingUi();const overlay=$("#settingsOverlay");overlay.classList.add("open");overlay.setAttribute("aria-hidden","false");$("#settingsClose").focus()}
function closeSettings(){const overlay=$("#settingsOverlay");overlay.classList.remove("open");overlay.setAttribute("aria-hidden","true");modalReturnFocus?.focus?.();modalReturnFocus=null}
function switchSettingsTab(name){const titles={general:"Chung",appearance:"Giao diện",ai:"AI & Model",data:"Dữ liệu"};$$('.settings-tab').forEach(button=>button.classList.toggle('active',button.dataset.settingsTab===name));$$('.settings-pane').forEach(pane=>pane.classList.toggle('active',pane.dataset.settingsPane===name));$("#settingsPaneTitle").textContent=titles[name]||"Cài đặt"}
function contextStatusText(state){return CONTEXT_STATUS_TEXT[state]||"Không thể xử lý"}
function contextSourceName(source){return typeof source==="string"?source:source?.filename||"Tệp"}
function contextSourcesForRequest(){if(!$("#context").value.trim())return [];const active=[...contextAttachments.values()].filter(item=>item.status==="ready"&&item.source).map(item=>({...item.source}));return active.length?active:persistedContextSources.map(source=>({...source}))}
function contextAttachmentPending(){return [...contextAttachments.values()].some(item=>item.status==="loading"||item.status==="processing")}
function rebuildContextFromAttachments(){
  const ready=[...contextAttachments.values()].filter(item=>item.status==="ready"&&item.source&&typeof item.text==="string");
  $("#context").value=ready.map(item=>`===== ${item.source.filename} =====\n${item.text}`).join("\n\n--- attached file ---\n\n");
}
function updateFileChipSummary(){
  const chip=$("#chatFileChip"),name=chip.querySelector(".file-name"),status=chip.querySelector(".file-status"),items=[...contextAttachments.values()];
  if(!items.length){chip.className="file-chip";name.textContent="";status.textContent="";return}
  const first=items[0],ready=items.filter(item=>item.status==="ready").length,hasError=items.some(item=>item.status==="error"||item.status==="unsupported");
  chip.className=`file-chip show${hasError?" error":""}`;name.textContent=items.length===1?first.filename:`${items.length} tệp đính kèm`;status.className=`file-status${hasError?" error":""}`;status.textContent=items.length===1?contextStatusText(first.status):`${ready}/${items.length} Sẵn sàng`;
  const retry=chip.querySelector(".file-retry"),remove=chip.querySelector(".file-remove");retry.disabled=!hasError;remove.disabled=false;retry.setAttribute("aria-label",items.length===1?`Thử lại tệp ${first.filename}`:"Thử lại tệp lỗi");remove.setAttribute("aria-label",items.length===1?`Bỏ tệp ${first.filename}`:"Bỏ tệp đính kèm");
}
function renderContextAttachments(){
  const list=$("#contextFileList");
  if(list){const active=[...contextAttachments.values()],saved=active.length?[]:persistedContextSources.map((source,index)=>({id:`saved_${index}`,filename:contextSourceName(source),status:"ready",source,saved:true})),items=active.length?active:saved;list.innerHTML=items.length?items.map(item=>`<div class="context-file-row ${item.status}" data-context-file-id="${esc(item.id)}" role="listitem"><div class="context-file-main"><b title="${esc(item.filename)}">${esc(item.filename)}</b><span class="context-file-state">${contextStatusText(item.status)}</span>${item.saved?"<small>Đã lưu cùng cuộc trò chuyện</small>":item.error?`<small>${esc(item.error)}</small>`:""}</div><div class="context-file-actions"><button type="button" class="context-file-retry" ${item.saved||item.status==="loading"||item.status==="processing"?"disabled":""}>${item.saved?"Đã nạp":"Thử lại"}</button><button type="button" class="context-file-remove" aria-label="Bỏ tệp ${esc(item.filename)}">×</button></div></div>`).join(""):"<div class=\"context-file-empty\">Chưa có tệp đính kèm.</div>";
    list.querySelectorAll(".context-file-row").forEach(row=>{const id=row.dataset.contextFileId;row.querySelector(".context-file-retry").onclick=()=>retryContextFile(id);row.querySelector(".context-file-remove").onclick=()=>removeContextAttachment(id)})
  }
  updateFileChipSummary();
}
function setFileChipState(state,file,message=""){
  const chip=$("#chatFileChip"),status=chip.querySelector(".file-status");chip.className=`file-chip show ${state==="error"||state==="unsupported"?"error":""}`;chip.querySelector(".file-name").textContent=file?.name||"Tệp";status.className=`file-status${state==="error"||state==="unsupported"?" error":""}`;status.textContent=message||contextStatusText(state)
}
async function encodeFileBase64(file){
  const bytes=new Uint8Array(await file.arrayBuffer());let binary="";
  for(let offset=0;offset<bytes.length;offset+=0x8000)binary+=String.fromCharCode(...bytes.subarray(offset,Math.min(offset+0x8000,bytes.length)));
  return btoa(binary)
}
async function contextResponseError(response){
  try{const data=await response.json(),detail=data?.detail;return typeof detail==="object"?{code:detail.code||"CONTEXT_ERROR",message:detail.message||"Không thể xử lý tệp."}:{code:"CONTEXT_ERROR",message:"Không thể xử lý tệp."}}
  catch{return {code:"CONTEXT_ERROR",message:"Không thể xử lý tệp."}}
}
async function processContextFile(file,id=null){
  if(!file)return false;
  persistedContextSources=[];
  const attachmentId=id||`context_${++contextAttachmentSequence}`,item=contextAttachments.get(attachmentId)||{id:attachmentId,file,filename:file.name,status:"loading",text:"",source:null,error:""};item.file=file;item.filename=file.name;item.status="loading";item.text="";item.source=null;item.error="";contextAttachments.set(attachmentId,item);activeContextFile=file;rebuildContextFromAttachments();renderContextAttachments();
  try{
    await Promise.resolve();
    if(Number(file.size)>MAX_CONTEXT_FILE_BYTES_V1){const error=new Error(`Tệp vượt giới hạn ${MAX_CONTEXT_FILE_BYTES_V1.toLocaleString()} byte.`);error.code="FILE_TOO_LARGE";throw error}
    item.status="processing";renderContextAttachments();
    const response=await fetch("/api/context/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:file.name,content_base64:await encodeFileBase64(file)})});
    if(!response.ok){const detail=await contextResponseError(response),error=new Error(detail.message);error.code=detail.code;throw error}
    const prepared=await response.json();if(prepared?.status!=="ready"||typeof prepared.text!=="string"||!prepared.source?.filename){const error=new Error("Bộ xử lý tệp trả về dữ liệu không hợp lệ.");error.code="PARSER_FAILED";throw error}if(!contextAttachments.has(attachmentId))return false;
    item.status="ready";item.text=prepared.text;item.source=prepared.source;item.error="";rebuildContextFromAttachments();renderContextAttachments();toast(`Đã nạp ${file.name} vào ngữ cảnh`,"success");return true
  }catch(error){
    if(!contextAttachments.has(attachmentId))return false;
    item.status=error.code==="UNSUPPORTED_FORMAT"?"unsupported":"error";item.error=error.message||"Không thể xử lý tệp.";renderContextAttachments();return false
  }
}
function retryContextFile(id){const item=contextAttachments.get(id);if(item&&! ["loading","processing"].includes(item.status))processContextFile(item.file,id)}
function removeContextAttachment(id){if(String(id).startsWith("saved_")){persistedContextSources=[];$("#context").value="";renderContextAttachments();return}if(!contextAttachments.has(id))return;contextAttachments.delete(id);activeContextFile=[...contextAttachments.values()][0]?.file||null;rebuildContextFromAttachments();renderContextAttachments()}
function clearContextFile(){activeContextFile=null;contextAttachments.clear();persistedContextSources=[];const chip=$("#chatFileChip");chip.className="file-chip";chip.querySelector(".file-name").textContent="";chip.querySelector(".file-status").textContent="";$("#contextFile").value="";const list=$("#contextFileList");if(list)list.innerHTML="<div class=\"context-file-empty\">Chưa có tệp đính kèm.</div>"}
function installResizer(handle,target,{min=300,max=720,cssVariable=null}={}){if(!handle||!target)return;let startX=0,startWidth=0;handle.addEventListener("pointerdown",event=>{if(innerWidth<=900)return;startX=event.clientX;startWidth=target.getBoundingClientRect().width;handle.classList.add("resizing");handle.setPointerCapture(event.pointerId)});handle.addEventListener("pointermove",event=>{if(!handle.classList.contains("resizing"))return;const width=Math.max(min,Math.min(max,startWidth-(event.clientX-startX)));if(cssVariable)document.documentElement.style.setProperty(cssVariable,`${width}px`);else target.style.width=`${width}px`});handle.addEventListener("pointerup",event=>{handle.classList.remove("resizing");try{handle.releasePointerCapture(event.pointerId)}catch{}})}

$$('.ins-tab').forEach((button,index)=>{button.onclick=()=>switchInspectorTab(button.dataset.tab);button.onkeydown=event=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;event.preventDefault();const tabs=$$('.ins-tab');let next=index;if(event.key==="ArrowLeft")next=(index-1+tabs.length)%tabs.length;if(event.key==="ArrowRight")next=(index+1)%tabs.length;if(event.key==="Home")next=0;if(event.key==="End")next=tabs.length-1;switchInspectorTab(tabs[next].dataset.tab);tabs[next].focus()}});
$$('.example').forEach(button=>button.onclick=()=>{promptEl.value=button.dataset.prompt;autoSize();promptEl.focus()});
$("#attachButton").onclick=()=>$("#contextFile").click();$("#closeContext").onclick=()=>setContextOpen(false,true);$("#clearContext").onclick=()=>{$("#context").value="";clearContextFile();toast("Đã xóa ngữ cảnh")};$("#contextFile").onchange=async event=>{const files=[...event.target.files];if(files.length){$("#context").value="";await Promise.all(files.map(file=>processContextFile(file)))}event.target.value=""};$("#chatFileChip .file-retry").onclick=()=>{const item=[...contextAttachments.values()].find(item=>item.file===activeContextFile);if(item)retryContextFile(item.id);else if(activeContextFile)processContextFile(activeContextFile)};$("#chatFileChip .file-remove").onclick=()=>{const item=[...contextAttachments.values()].find(item=>item.file===activeContextFile);if(item)removeContextAttachment(item.id);else{$("#context").value="";clearContextFile()}};
$("#sidebarToggle").onclick=()=>{if(innerWidth<=900){app.classList.remove("mobile-side-open");updatePanelButtons();return}app.classList.toggle("side-collapsed");persistPanels()};$("#inspectorToggle").onclick=()=>{if(innerWidth<=900){app.classList.remove("mobile-side-open");app.classList.toggle("mobile-ins-open")}else app.classList.toggle("ins-collapsed");persistPanels()};$("#inspectorClose").onclick=closeInspector;$("#mobileSidebar").onclick=()=>{app.classList.remove("mobile-ins-open");app.classList.toggle("mobile-side-open");updatePanelButtons()};$("#panelScrim").onclick=closeMobilePanels;$("#newChat").onclick=newConversation;
$("#provider").onchange=()=>{localStorage.setItem("adaptive.provider",$("#provider").value);populateModels()};$("#model").onchange=()=>{localStorage.setItem(`adaptive.model.${$("#provider").value}`,selectedModel());updateProviderDisplay()};$("#providerCheck").onclick=testProvider;$("#compareBtn").onclick=openCompare;$("#closeCompare").onclick=closeCompare;$("#compareModal").onclick=e=>{if(e.target===$("#compareModal"))closeCompare()};$("#runCompare").onclick=runCompare;$("#exportBtn").onclick=()=>{$("#advancedMenu").open=false;if(currentRunId)downloadRun(currentRunId)};
$("#quickRerun").onclick=rerunSelectedQuestion;$("#openEvidence").onclick=()=>{closeInspector();openContextScreen("executionEvidence")};$("#detailCopy").onclick=()=>{const selected=$(".turn-card.selected-run")||$$('.turn-card').at(-1),answer=selected?.querySelector(".answer-body")?.innerText?.trim();if(!answer){toast("Chưa có câu trả lời để sao chép.","error");return}navigator.clipboard.writeText(answer).then(()=>toast("Đã sao chép câu trả lời","success"))};
$$('[data-close-context]').forEach(button=>button.onclick=closeContextScreens);$("#openComparisonReport").onclick=()=>{closeCompare();openContextScreen("comparisonReport")};$("#compareCopy").onclick=()=>{const fixed=compareResult("fixed"),adaptive=compareResult("adaptive");if(!fixed&&!adaptive){toast("Chưa có kết quả so sánh để sao chép.","error");return}const text=`Cố định (Fixed)\n${compareAnswer(fixed,2000)}\n\nAdaptive Agent\n${compareAnswer(adaptive,2000)}`;navigator.clipboard.writeText(text).then(()=>toast("Đã sao chép so sánh","success"))};
$("#rawCopyBtn").onclick=()=>navigator.clipboard.writeText($("#rawEvents").textContent||"[]").then(()=>toast("Đã sao chép evidence an toàn","success"));$("#rawDownloadBtn").onclick=downloadCurrentEvidence;
$("#modelMenuButton").onclick=event=>{event.stopPropagation();toggleAnchoredPopover($("#modelMenuButton"),$("#modelMenu"))};$("#modelMenu").onclick=event=>event.stopPropagation();$("#searchChat").onclick=()=>{const opened=toggleAnchoredPopover($("#searchChat"),$("#searchPopover"));if(opened){renderSearchResults($("#searchInput").value);$("#searchInput").focus()}};$("#searchInput").oninput=event=>renderSearchResults(event.target.value);
$("#settingsButton").onclick=openSettings;$("#settingsClose").onclick=closeSettings;$("#settingsOverlay").onclick=event=>{if(event.target===$("#settingsOverlay"))closeSettings()};$$('.settings-tab').forEach(button=>button.onclick=()=>switchSettingsTab(button.dataset.settingsTab));$$('.switch').forEach(button=>button.onclick=()=>{const on=!button.classList.contains('on');button.classList.toggle('on',on);button.setAttribute('aria-pressed',String(on))});
$("#helpButton").onclick=()=>toggleAnchoredPopover($("#helpButton"),$("#helpPopover"));$$('[data-help]').forEach(button=>button.onclick=()=>{const text={usage:"Gửi câu hỏi; chọn mô hình và cách xử lý trong menu.",files:"Hỗ trợ TXT, Markdown, JSON, CSV và các file text/source PY, JS, TS, HTML, CSS.",modes:"Tự động để Adaptive Agent chọn cách xử lý; bạn cũng có thể chọn chế độ cố định.",about:"Adaptive Agent là ứng dụng local dùng FastAPI và bằng chứng thực thi thật."}[button.dataset.help];toast(text)});$("#shareButton").onclick=()=>toggleAnchoredPopover($("#shareButton"),$("#sharePopover"));$("#profile").onclick=()=>toggleAnchoredPopover($("#profile"),$("#accountMenu"));
$("#renameForm").onsubmit=event=>{event.preventDefault();confirmRenameConversation()};$("#cancelRename").onclick=closeRenameDialog;$("#renameDialog").onclick=event=>{if(event.target===$("#renameDialog"))closeRenameDialog()};$("#cancelDelete").onclick=closeDeleteConfirm;$("#confirmDelete").onclick=confirmDeleteConversation;$("#deleteConfirm").onclick=event=>{if(event.target===$("#deleteConfirm"))closeDeleteConfirm()};document.addEventListener("click",event=>{if(!event.target.closest(".anchor-pop,.sidebar-popover,.account-menu,.model-menu,#searchChat,#helpButton,#shareButton,#profile,#modelMenuButton"))closeFloatingUi();if(!event.target.closest(".thread-menu"))closeConversationMenus()});$("#threads").addEventListener("scroll",()=>closeConversationMenus(),{passive:true});
installResizer($("#inspectorResizer"),$("#inspector"),{min:300,max:620,cssVariable:"--locked-detail"});installResizer($("#compareResizer"),$("#compareModal"),{min:520,max:900});
promptEl.oninput=autoSize;promptEl.onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();runChat()}};sendBtn.onclick=runChat;
window.addEventListener("resize",()=>{updatePanelButtons();closeConversationMenus();if($("#modelMenu").classList.contains("open"))positionModelMenu()});
window.addEventListener("keydown",event=>{const modal=$("#compareModal"),settings=$("#settingsOverlay");if(event.key==="Escape"){if($$(".context-screen.open").length){closeContextScreens();return}if($("#renameDialog").classList.contains("open")){closeRenameDialog();return}if($("#deleteConfirm").classList.contains("open")){closeDeleteConfirm();return}if(settings.classList.contains("open")){closeSettings();return}if(modal.classList.contains("open")){closeCompare();return}if($("#contextDrawer").classList.contains("open")){setContextOpen(false,true);return}if(app.classList.contains("mobile-side-open")||app.classList.contains("mobile-ins-open")){closeMobilePanels();return}closeFloatingUi();$("#advancedMenu").open=false}if(event.key==="Tab"&&(modal.classList.contains("open")||settings.classList.contains("open"))){const scope=settings.classList.contains("open")?settings:modal,focusables=[...scope.querySelectorAll('button:not([disabled]),[href],select,textarea,[tabindex]:not([tabindex="-1"])')].filter(node=>node.offsetParent!==null);if(!focusables.length)return;const first=focusables[0],last=focusables.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}}});
async function boot(){mountEvidenceWorkspace();restorePanels();switchInspectorTab(["graph","agents","metrics","raw","context"].includes(localStorage.getItem(INSPECTOR_TAB_KEY))?localStorage.getItem(INSPECTOR_TAB_KEY):"graph");renderComparisonSurfaces();await loadConfig();await loadConversations(true);promptEl.focus()}
boot().catch(error=>toast("Không khởi tạo được app: "+error.message,"error"));
