import asyncio, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from app.providers.fake import FakeProvider
from app.core.types import RunState,Budget
from app.core.orchestrator import Orchestrator
from app.core.rag import frozen_snapshot

async def main():
    ev=[]
    async def emit(x): ev.append(x)
    src="Authentication\nAccess tokens expire after 60 minutes. Refresh tokens only for confidential clients. Public clients re-authenticate.\n\nPagination\nDefault 25 max 100.\n\nErrors\n401 auth, 429 rate limit."
    task="Phân tích Authentication, Pagination và Error Handling."
    snap,meta=frozen_snapshot(task,src)
    st=RunState(strategy="adaptive",provider="fake",model="fake-research-v2",task=task,context=snap,retrieval_meta=meta)
    o=Orchestrator(FakeProvider(),emit,budget=Budget())
    await o.run(st)
    print(st.status, st.stop_reason, o.metrics(st))
    print([x["event"]["title"] for x in ev if x.get("type")=="trace" and x["event"]["kind"] in ("decision","scheduler","verification","stop")])
    assert st.status=="completed"
    assert st.stop_reason=="STOP_SUFFICIENT"
    assert any(x.get("event",{}).get("title")=="AUTO route selected" for x in ev)
if __name__=="__main__": asyncio.run(main())
