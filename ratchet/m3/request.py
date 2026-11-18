"""Fixed-order request filling, section caps and protected rider reservation."""
from copy import deepcopy
import json
from ..core import count,ENC
ORDER=('primary_card','accounting','ledger','segment_slice','prefix_summary','riders','history')
SECTION_LIMITS={'primary_card':1500,'accounting':800,'segment_slice':4000,'prefix_summary':1500}
RIDER_RESERVE_PER_TARGET=250

def sanitize(value,contract=True):
    if isinstance(value,dict):return {k:sanitize(v,contract) for k,v in value.items() if k not in ('cost','Cost','I_form','Hold','p_clr') and (contract or k not in ('contract','prior_window_constraints','forbid','forbidden_operations'))}
    if isinstance(value,list):return [sanitize(v,contract) for v in value]
    return value

def assemble(parts,B=12000,rider_count=0,limits=None):
    limits=dict(SECTION_LIMITS if limits is None else limits)
    texts={k:v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,separators=(',',':')) for k,v in parts.items() if k in ORDER}
    capped=[];truncated=[]
    for k,limit in limits.items():
        if count(texts.get(k,''))>limit:texts[k]=ENC.decode(ENC.encode(texts[k])[:limit]);capped.append(k)
    reserve=RIDER_RESERVE_PER_TARGET*rider_count
    protected=min(count(texts.get('riders','')),reserve)
    def text():return '\n'.join('['+k+']\n'+texts[k] for k in ORDER if texts.get(k))
    if reserve>B:raise ValueError('rider reservation exceeds request budget')
    # Reserve the promised capacity even if a concise rider description uses less.
    target=B-max(0,reserve-protected)
    for key in reversed(ORDER):
        if count(text())<=target:break
        if not texts.get(key):continue
        floor=protected if key=='riders' else 0
        tokens=ENC.encode(texts[key]);keep=max(floor,len(tokens)-(count(text())-target)-8)
        if keep<len(tokens):texts[key]=ENC.decode(tokens[:keep]);truncated.append(key)
    while count(text())>target:
        key=next((k for k in reversed(ORDER) if count(texts.get(k,''))>(protected if k=='riders' else 0)),None)
        if key is None:raise ValueError('protected sections cannot fit')
        texts[key]=ENC.decode(ENC.encode(texts[key])[:-1])
        if key not in truncated:truncated.append(key)
    return dict(text=text(),part_tokens={k:count(texts.get(k,'')) for k in ORDER},label_and_separator_tokens=count(text())-sum(count(v) for v in texts.values()),total_tokens=count(text()),truncated=truncated+[k for k in capped if k not in truncated],capped=capped,section_limits=limits,rider_reserved_tokens=reserve,rider_retained_tokens=count(texts.get('riders','')))


def segmented_slice(tracker,seeds,boundary_registers):
    from collections import deque
    from ratchet.slicing.patcher import patch
    boundaries={tuple(v) for v in boundary_registers};queue=deque(tuple(v) for v in seeds);visited=set();selected=set()
    while queue:
        key=queue.popleft()
        if key in visited or tracker.excluded(key[1]):continue
        visited.add(key)
        if key in boundaries:continue
        for sid in sorted(tracker.index.get(key,())):
            # A statement whose LHS is the frozen state belongs to the prefix.
            st=tracker.statements[sid]
            if any((st.module,name) in boundaries for name in st.lhs):continue
            selected.add(sid)
            for name in st.signals:
                if not tracker.excluded(name):queue.append((st.module,name))
        queue.extend(sorted(tracker.links.get(key,())))
    sliced=dict(statement_ids=sorted(selected),definitions=tracker.required_definitions(sorted(selected)))
    return dict(text=patch(tracker,sliced),boundary_registers=[list(v) for v in sorted(boundaries)],seeds=[list(v) for v in seeds],retained_signals=[list(v) for v in sorted(visited)],statement_ids=sorted(selected))


def prefix_summary(entry,cards,contract=True,count_instructions=None,key_state_registers=None):
    from ..m2.render import expression,contract_text
    if count_instructions is None:
        from ..dut_api import DUTAdapter
        count_instructions=DUTAdapter().count_instructions
    state=entry.get('key_state',{})
    if key_state_registers is not None:
        state={key:state[key] for key in key_state_registers(state) if key in state}
    lines=['Prefix primitive count: '+str(len(entry['prefix'])),'Key register state: '+json.dumps(state,ensure_ascii=False),'Last 20 prefix instructions:',''.join([line for line in entry['prefix'] if count_instructions(line)>0][-20:])]
    held=list(entry.get('held_checkpoints',[]))
    if entry.get('checkpoint') in cards and entry['checkpoint'] not in held:held.append(entry['checkpoint'])
    lines+=['Established checkpoints and constraints:']+[contract_text(cards[c]) if contract else expression(cards[c]['predicate']['expr']) for c in held if c in cards]
    return '\n'.join(lines)

def compile_failure_stop(statuses):
    return len(statuses)>=8 and sum(s=='compile_fail' for s in statuses)>len(statuses)/2
