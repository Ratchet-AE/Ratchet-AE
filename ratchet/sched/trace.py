"""Streaming native trace reader, including failed-run regression and CF stops."""
import json,shutil,subprocess
from pathlib import Path
from ..lib.source_map import source_map

def execution_rows(out):
    p=out/'trace.jsonl'
    if p.exists() and p.stat().st_size:
        with p.open() as f:
            for line in f:yield json.loads(line)
        return
    p=out/'instruction_trace.log'
    if not p.exists():
        matches=list(out.glob('trace_core*.log'))
        if len(matches)!=1:raise ValueError('missing/ambiguous native instruction trace')
        p=matches[0]
    with p.open() as f:
        for line in f:
            cols=line.split()
            if len(cols)>=4 and cols[0].isdigit():yield dict(cycle=int(cols[1]),pc=cols[2],instruction=cols[3])

def metadata(out,test,workspace=None):
    out=Path(out);cache=out/'pc_to_primitive.json'
    if cache.exists():return json.loads(cache.read_text())
    work=Path(workspace) if workspace else out
    if (work/'pc_to_primitive.json').exists():return json.loads((work/'pc_to_primitive.json').read_text())
    work.mkdir(parents=True,exist_ok=True)
    if work!=out:
        (work/'build').mkdir(exist_ok=True);shutil.copyfile(out/'build/compile_command.json',work/'build/compile_command.json')
    if not (work/'trace.jsonl').exists():
        with (work/'trace.jsonl').open('w') as f:
            for row in execution_rows(out):f.write(json.dumps(row)+'\n')
    return source_map(work,test)

def monitor_timing(out):
    # The monitor counts all clock edges; ibex_tracer.cycle resets.
    # The first post-reset monitor row is tracer cycle zero (nonblocking RTL).
    first=[]
    with (out/'ratchet_monitor.jsonl').open() as f:
        for _,line in zip(range(32),f):first.append(json.loads(line))
    release=first[0]['cycle'] if first else 0
    for a,b in zip(first,first[1:]):
        if b['cycle']>a['cycle']+1:release=b['cycle'];break
    p=out/'ratchet_monitor.jsonl'
    with p.open('rb') as f:
        f.seek(max(0,p.stat().st_size-65536));tail=f.read().splitlines()
    final=None
    for line in reversed(tail):
        try:final=json.loads(line);break
        except ValueError:pass
    status=[];sp=out/'ibex_status.jsonl'
    if sp.exists():
        for line in sp.open():
            try:status.append(json.loads(line))
            except ValueError:pass
    end=next((r for r in reversed(status) if r.get('event')=='final'),None)
    offset=final['cycle']-end['cycle'] if final and end else 0
    return release,[(r['cycle']+offset,r) for r in status if r.get('event')=='trap']

def iter_trace(out,test,workspace=None):
    out=Path(out);mapping=metadata(out,test,workspace);executed=iter(execution_rows(out));next_row=next(executed,None);index=-1
    release,trap_rows=monitor_timing(out);traps=iter(trap_rows);next_trap=next(traps,None);last_trap=None
    # Trace cache keys are fixed-width hexadecimal PCs.
    source_lines=test['asm'].splitlines(keepends=True)
    with (out/'ratchet_monitor.jsonl').open() as f:
        for line in f:
            row=json.loads(line)
            trace_cycle=row.get('trace_cycle',row['cycle']-release)
            while next_row is not None and next_row['cycle']<=trace_cycle:
                if next_row['pc'] in mapping:index=mapping[next_row['pc']]
                next_row=next(executed,None)
            while next_trap is not None and next_trap[0]<=row['cycle']:
                last_trap=next_trap;next_trap=next(traps,None)
            if last_trap and row['cycle']-last_trap[0]<=2:
                event=last_trap[1];pc=format(event['mepc'],'08x');cause_index=mapping.get(pc)
                row['clear_input']=dict(index=cause_index,pc=pc,cause=event.get('cause'),interrupt=event.get('interrupt'),input=source_lines[cause_index] if cause_index is not None else 'unmapped exception/interrupt PC')
                if cause_index is not None:row['cause_index']=cause_index
            row['trace_cycle']=trace_cycle
            row['index']=index
            if index<0 or not row.get('reset_released',True):continue
            row['reset_released']=True
            row['state']={k:int(v,16) for k,v in row['state'].items()};row['clear_guards']={k:bool(v) for k,v in row['clear_guards'].items()};row['conditions']={k:bool(v) for k,v in row['conditions'].items()}
            yield row

def read_trace(out,test,workspace=None,compact=False,focus=None):
    if not compact:return list(iter_trace(out,test,workspace))
    result=[];last=None;last_signature=None
    for row in iter_trace(out,test,workspace):
        if focus:
            cid,guards=focus;signature=(row['conditions'].get(cid),row['measures'].get(cid),tuple(row['clear_guards'].get(g) for g in guards),tuple(row['conditions'].items()) if row['conditions'].get(cid) else ())
        else:signature=(tuple(row['conditions'].items()),tuple(row['measures'].items()),tuple(row['clear_guards'].items()),tuple(row.get('sigma',{}).items()))
        # Within an identical observation run retain its earliest state (tie
        # behavior), plus the last row before the next transition and at EOF.
        if signature!=last_signature:
            if last is not None and (not result or last['cycle']!=result[-1]['cycle']):result.append(last)
            result.append(row);last_signature=signature
        last=row
    if last is not None and (not result or last['cycle']!=result[-1]['cycle']):result.append(last)
    return result
