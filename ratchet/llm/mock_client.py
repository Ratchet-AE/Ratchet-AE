"""Deterministic synthetic model/executor. Never hardware-coverage evidence."""
import json
from ..core import count
from ..expressions import evaluate,signals
class MockModel:
    is_mock=True
    def __init__(self):self.calls=0;self.requests=[]
    def __call__(self,request,schema,N,level,context):
        self.calls+=1;self.requests.append(dict(level=level,text=request,N=N,schema=schema))
        asm='addi x5, x5, 1\n'*max(40,min(context['maximum'],40))
        if level=='0':parsed=dict(rationale='isolated synthetic mock; not method evidence',asm=asm)
        else:parsed=dict(candidates=[dict(primary_target=context['cohort']['primary'],rationale='isolated synthetic mock; not method evidence',suffix=asm) for _ in range(N)])
        output=count(json.dumps(parsed));return dict(parsed=parsed,tokens=count(request)+output,output_tokens=output)
class MockExecutor:
    def __init__(self,bundle,outside_hit=None):self.bundle=bundle;self.calls=0;self.outside_hit=outside_hit
    def __call__(self,test,context):
        self.calls+=1;raw={s for c in self.bundle.conditions.values() for s in signals(c['expr'])}
        for card in self.bundle.cards.values():raw.update(card['registers']);raw.add(card['measure']['signal'])
        state={s:0 for s in raw};observed={cid:bool(evaluate(c['expr'],state)) for cid,c in self.bundle.conditions.items()}
        rows=[]
        for cycle in (1,2,3):rows.append(dict(cycle=cycle,index=cycle-1,state=state.copy(),conditions=observed.copy(),measures={cid:1 if observed[card['predicate']['id']] else 0 for cid,card in self.bundle.cards.items()},clear_guards={},sigma={}))
        # Hits correspond to exact sampled predicates; synthetic only.
        hits=[bid for bid,spec in self.bundle.specs.items() if any(all(observed.get(cid,False) for cid in alt['condition_ids']) for alt in spec.get('hit_alternatives',[]))]
        if self.outside_hit:hits.append(self.outside_hit)
        return dict(status='ok',hits=hits,line_hits=[],rows=rows,retirements=[dict(cycle=r['cycle'],held=[cid for cid,c in self.bundle.cards.items() if r['conditions'].get(c['predicate']['id'])]) for r in rows],evidence_test_id='mock:'+str(self.calls),evidence_scope='synthetic_mock',selftest_only=True,change_class='same_mock_suffix')
