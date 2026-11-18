"""Reverse driver traversal; return only sequential registers."""
from collections import deque
def sequential_dependencies(tracker,seeds):
    queue=deque(tuple(s) for s in seeds);seen=set();registers=set();drivers=[]
    while queue:
        key=queue.popleft()
        if key in seen or tracker.excluded(key[1]):continue
        seen.add(key)
        for sid in tracker.drivers.get(key,()):
            s=tracker.statements[sid]
            if key[0]!=s.module or key[1] not in s.lhs:continue
            drivers.append(sid)
            if s.sequential:registers.add(key)
            queue.extend((s.module,n) for n in s.signals if n not in s.lhs and not tracker.excluded(n))
        queue.extend(tracker.reverse_links.get(key,()))
    return dict(registers=sorted(registers),driver_statement_ids=sorted(set(drivers)),visited=len(seen))
