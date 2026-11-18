"""Checkpoint frontier, stable cuts and counterfactual regression diagnosis."""
from pathlib import Path
import json,time
from ratchet.llm.ledger import append
def value(state,key):
    key='.'.join(key) if isinstance(key,(list,tuple)) else key
    v=state.get(key,state.get(key.rsplit('.',1)[-1]))
    if isinstance(v,str):
        try:return int(v,16)
        except ValueError:return None
    return v
def predicate(cp,state,enums=None):
    actual=value(state,cp['register']);expected=cp.get('value');op=cp['op']
    if actual is None:return False
    if op=='eq_enum':
        module=cp['register'][0];enums=enums or {}
        resolve=lambda v:enums.get(module+'.'+v,enums.get(v,v))
        expected=resolve(expected)
        if cp.get('path'):
            values=[resolve(v) for v in cp['path']]
            return actual in values and values.index(actual)>=cp['position']
    if op=='ge_fraction':
        threshold=value(state,cp['threshold_register'])
        return threshold is not None and actual>=threshold*cp['fraction']
    if isinstance(expected,str):
        expected=(enums or {}).get(cp['register'][0]+'.'+expected,(enums or {}).get(expected))
    if expected is None:return False
    if op=='ge':return actual>=expected
    return actual==expected
def snapshots(trace):
    state={};last_index=0;aliases={}
    for row in trace:
        if 'state' in row:state.update(row['state'])
        if 'register' in row:
            register=row['register'];path=row.get('path')
            if path:
                state[path]=row['value'];aliases.setdefault(register,path)
                if aliases[register]==path:state[register]=row['value']
            else:state[register]=row['value']
        last_index=row.get('index',last_index)
        yield dict(index=last_index,cycle=row.get('cycle',0),state=dict(state))
def diagnose(trace,chain,enums=None):
    trace=list(trace)
    if enums is None and trace:enums=trace[0].get('_enums',{})
    rows=list(snapshots(trace));truth=[[predicate(c,r['state'],enums) for c in chain] for r in rows]
    frontier=-1
    for i in range(len(chain)):
        if any(all(t[:i+1]) for t in truth):frontier=i
        else:break
    # Stable cuts are established for the whole prefix of checkpoint predicates.
    cut=None
    if frontier>=0:
        for i,row in enumerate(rows):
            if all(all(t[:frontier+1]) for t in truth[i:]):cut=row['index'];break
    def progress(cp,state):
        actual=value(state,cp['register'])
        if actual is None:return None
        if cp['op']=='eq_enum' and cp.get('path'):
            module=cp['register'][0];ev=enums or {};states=[ev.get(module+'.'+s,ev.get(s,s)) for s in cp['path']]
            return states.index(actual) if actual in states else -1
        if cp['op']=='target_value':return int(predicate(cp,state,enums))
        return actual
    regressions=[]
    for i in range(1,len(rows)):
        seen=set()
        for j,cp in enumerate(chain):
            identity=(tuple(cp['register']),cp.get('pattern',cp['op']))
            if identity in seen:continue
            seen.add(identity);previous=progress(cp,rows[i-1]['state']);current=progress(cp,rows[i]['state'])
            if previous is not None and current is not None and current<previous:
                reason={'counter_threshold':'counter_decrease_or_clear','history_accumulation':'confidence_decrease','fsm_deep_state':'earlier_path_state','configuration_gate':'gate_rewrite'}.get(cp.get('pattern'),'progress_decrease_or_clear')
                idx=rows[i]['index'];regressions.append(dict(event_id=len(regressions),index=idx,cycle=rows[i]['cycle'],checkpoint=j,previous=previous,current=current,candidates=list(range(max(0,idx-8),idx+1)),reason=reason))
    segment=min(frontier+1,len(chain)-1) if chain else None
    peak=max((progress(chain[segment],r['state']) or 0 for r in rows),default=0) if segment is not None else 0
    aliases={}
    for row in trace:
        if row.get('path'):aliases.setdefault(row['register'],row['path'])
    return dict(frontier=frontier,cut_index=cut,segment=segment,progress_peak=peak,regressions=regressions,instance_aliases=aliases)
def confirm_regressions(diagnostic,replay,out_dir,run_id='',test_id=''):
    """replay(removed_index, stop_cycle) -> diagnostic from a fresh reset replay.

    Callback output is diagnostic-only and never passed to coverage union.
    At most four replays are used for each regression event.
    """
    confirmed=[];root=Path(out_dir)
    for event in diagnostic['regressions']:
        for removed in list(reversed(event['candidates']))[:4]:
            start=time.monotonic();result=replay(removed,event['cycle']);elapsed=time.monotonic()-start
            # Match this transition; unrelated earlier/startup drops are distinct.
            gone=result.get('valid',True) and not any(r['cycle']<=event['cycle'] and r['checkpoint']==event['checkpoint'] and r['previous']>=event['previous'] and r['current']<=event['current'] for r in result['regressions'])
            append(root/'cf_replays.csv','run_id test_id event_id removed_idx regression_gone t_sim_s'.split(),dict(run_id=run_id,test_id=test_id,event_id=event['event_id'],removed_idx=removed,regression_gone=gone,t_sim_s=elapsed))
            if gone:confirmed.append(dict(event=event,removed_index=removed,reason=event['reason'],t_sim_s=elapsed));break
    return confirmed
