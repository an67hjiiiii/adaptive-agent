from __future__ import annotations
from collections import defaultdict, deque

def validate_plan(subtasks: list[dict]):
    ids=[x["id"] for x in subtasks]
    if len(ids)!=len(set(ids)):
        raise ValueError("Duplicate subtask ID")
    known=set(ids)
    indeg={i:0 for i in ids}
    edges=defaultdict(list)
    for s in subtasks:
        for dep in s.get("depends_on",[]):
            if dep not in known:
                raise ValueError(f"Unknown dependency {dep}")
            if dep==s["id"]:
                raise ValueError("Self-loop")
            edges[dep].append(s["id"])
            indeg[s["id"]]+=1
    q=deque([i for i,d in indeg.items() if d==0])
    seen=[]
    while q:
        n=q.popleft(); seen.append(n)
        for nxt in edges[n]:
            indeg[nxt]-=1
            if indeg[nxt]==0:
                q.append(nxt)
    if len(seen)!=len(ids):
        raise ValueError("Cycle detected")
    return True

def ready_nodes(subtasks: list[dict], done: set[str]):
    result=[]
    for s in subtasks:
        if s["id"] in done: continue
        if all(dep in done for dep in s.get("depends_on",[])):
            result.append(s)
    return result
