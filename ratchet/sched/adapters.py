"""Explicit I/O adapters; importing or constructing them never sends a request."""
from pathlib import Path
import json,os,time
from unittest.mock import patch
from ..m3.request import segmented_slice
from ..expressions import signals
from ..paths import RUNS_DIR
from .trace import read_trace

class UnifiedCaller:
    is_mock=False
    def __init__(self,run,dry_run=False):self.run=Path(run);self.index=0;self.dry_run=dry_run
    def __call__(self,request,schema,N,level,context):
        from ratchet.llm.client import call_llm
        self.run.mkdir(parents=True,exist_ok=True);schema_path=self.run/'runtime_schema.json';schema_path.write_text(json.dumps(schema)+'\n')
        result=call_llm(self.run,f'call{self.index:05d}','gen',request,schema_path,dry_run=self.dry_run);self.index+=1
        if not result.ok:raise RuntimeError('model reply failed unified schema validation')
        return dict(parsed=result.parsed,tokens=result.usage['input']+result.usage['output'],output_tokens=result.usage['output'])

class NativeExecutor:
    def __init__(self,out,binary,bundle=None,seed=0):
        self.out=Path(out);self.binary=Path(binary);self.n=0;self.seed=seed
        if bundle is None:
            from .artifacts import Bundle
            bundle=Bundle(RUNS_DIR/'ibex'/'m1')
        self.bundle=bundle
    def __call__(self,test,context):
        from tb.harness.run_test import run_test
        out=self.out/f'test{self.n:05d}';self.n+=1
        with patch.dict(os.environ,{'LLMCMP_SIM_BINARY':str(self.binary)}),patch('tb.harness.ibex_status.observed_binary',side_effect=lambda p:p):
            result=run_test('ibex',test,self.seed,out,timeout_s=context['timeout_s'])
        if result['status'] in ('ok','trap_storm'):
            from tb.harness.union import parse_dat,in_scope
            result.update(hits=[k for k,v in json.loads((out/'func_hits.json').read_text()).items() if v>0],line_hits=[p['key'] for p in parse_dat(out/'line.dat') if p['hits'] and in_scope(p,'ibex')],rows=read_trace(out,test,compact=True))
            from .replay import IbexReplay
            result['replay']=IbexReplay(test,out,self.binary,self.bundle)
            from .evidence import retirements
            result['retirements']=retirements(out,test,result['rows'],self.bundle.cards)
            result['evidence_test_id']=str(out.relative_to(self.out.parent))
        return result

class TrackerSlice:
    def __init__(self,bundle,tracker=None):
        if tracker is None:
            from ratchet.slicing.tracker import Tracker
            tracker=Tracker.for_dut('ibex')
        self.bundle=bundle;self.tracker=tracker
    def __call__(self,bid,boundary,diagnostic):
        spec=self.bundle.specs[bid];missing=(diagnostic.get('conjunction') or {}).get('missing_conditions',[])
        names={s for c in missing for s in c['drivers']}
        if not names:names={s for a in spec['alternatives'] for cid in a['condition_ids'] for s in signals(self.bundle.conditions[cid]['expr'])}
        # The shared tracker uses definition-qualified (module,signal) keys.
        # Its resolver conservatively merges repeated instances, as in uvmb.
        def resolve(paths):
            leaves=[p.split('[')[0].rsplit('.',1)[-1] for p in paths]
            return self.tracker.resolve(leaves)
        return segmented_slice(self.tracker,resolve(names),resolve(boundary))
