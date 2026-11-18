"""Measured retirement evidence for held checkpoints; never infer counts from indices."""
from .trace import execution_rows,metadata,monitor_timing
from ..expressions import evaluate
def retirements(out,test,rows,cards):
 from pathlib import Path
 out=Path(out);mapping=metadata(out,test);release,_=monitor_timing(out);observations=iter(sorted(rows,key=lambda r:r['trace_cycle']));nxt=next(observations,None);state=None;result=[]
 for retired in execution_rows(out):
  while nxt is not None and nxt['trace_cycle']<=retired['cycle']:state=nxt;nxt=next(observations,None)
  if state is None or retired['pc'] not in mapping:continue
  if int(retired['instruction'],16) in (0x30200073,0x7b200073):continue
  held=[cid for cid,card in cards.items() if evaluate(card['predicate']['expr'],state.get('state',{})) is True]
  result.append(dict(cycle=retired['cycle']+release,held=held))
 return result

def attach(diagnostic,retired,test_id,rows,scope='native_trace'):
 if not test_id:return diagnostic
 for item in diagnostic.get('items',[]):
  if 'formed_cycle' not in item:continue
  start=item['formed_cycle'];end=item.get('window_end',item.get('loss_cycle',rows[-1]['cycle'] if rows else start))
  count=sum(start<=r['cycle']<=end and item['checkpoint'] in r['held'] for r in retired)
  item['evidence']=dict(test_id=test_id,held_instructions=count,window_start=start,window_end=end,target=diagnostic['bin'],scope=scope,measurement='user-program retirements within this target window; transition MRET/DRET excluded')
 return diagnostic
