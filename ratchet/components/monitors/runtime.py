"""Attach primitive indices to sparse bind logs; diagnose-only reset replays."""
from pathlib import Path
import json,bisect,os
from ratchet.components.m2_diag import diagnose
from ratchet.components.m3_repair import primitives
from ratchet.paths import RUNS_DIR
def read_trace(out,test,dut):
    out=Path(out);changes=[json.loads(l) for l in (out/'m1_changes.jsonl').read_text().splitlines()]
    if dut=='es':
        boundaries=[json.loads(l) for l in (out/'primitives.jsonl').read_text().splitlines() if json.loads(l).get('event')=='begin']
    else:
        if dut=='ibex' and not (out/'trace.jsonl').exists():
            raw=next(out.glob('trace_core*.log'));rows=[]
            for line in raw.read_text().splitlines():
                c=line.split()
                if len(c)>3 and c[0].isdigit():rows.append(dict(index=len(rows),cycle=int(c[1]),pc=c[2],instruction=c[3]))
            (out/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        boundaries=[json.loads(l) for l in (out/'trace.jsonl').read_text().splitlines()]
    if dut=='ibex':
        from ratchet.components.monitors.source_map import source_map
        mapping=source_map(out,test)
        boundaries=[dict(r,index=mapping.get(r['pc'],-1)) for r in boundaries];boundaries=[r for r in boundaries if r['index']>=0]
    cycles=[r['cycle'] for r in boundaries]
    for r in changes:
        i=bisect.bisect_right(cycles,r['cycle'])-1
        r['index']=boundaries[i]['index'] if i>=0 else -1
    result=[r for r in changes if r['index']>=0]
    manifest=RUNS_DIR/dut/'m1/monitor/signals.json'
    if result and manifest.exists():result[0]['_enums']=json.loads(manifest.read_text()).get('enum_values',{})
    return result
class ReplayProvider:
    def __init__(self,seed=0):self.index=0;self.seed=seed
    def __call__(self,dut,test,removed,stop_cycle,chain,run):
        from tb.harness.run_test import run_test
        from copy import deepcopy
        copy=deepcopy(test);units=primitives(test,dut)
        # Whole primitive deletion is an explicit diagnostic counterfactual.
        reduced=units[:removed]+units[removed+1:]
        if dut=='sd':copy['inputs']=reduced
        elif dut=='es':copy['ops']=reduced
        else:copy['asm']=''.join(reduced)
        out=Path(run)/f'cf_replays/replay{self.index:05d}';self.index+=1
        old=os.environ.get('LLMCMP_STOP_CYCLE');os.environ['LLMCMP_STOP_CYCLE']=str(stop_cycle)
        try:result=run_test(dut,copy,self.seed,out)
        finally:
            if old is None:os.environ.pop('LLMCMP_STOP_CYCLE',None)
            else:os.environ['LLMCMP_STOP_CYCLE']=old
        if not (out/'m1_changes.jsonl').exists():return dict(valid=False,regressions=[],error=result.get('error','No replay trace'))
        rows=[r for r in read_trace(out,copy,dut) if r['cycle']<=stop_cycle]
        return diagnose(rows,chain)
