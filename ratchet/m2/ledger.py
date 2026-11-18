"""Evidence-backed checkpoint ledger with resolved prerequisite constraints."""
from copy import deepcopy
import json
def proven(e):
 return isinstance(e,dict) and bool(e.get('test_id')) and isinstance(e.get('held_instructions'),int) and not isinstance(e.get('held_instructions'),bool) and e['held_instructions']>=0
def obsolete(e):return e.get('reason')=='suffix' or e.get('evidence')=='repeated_failure'
class Ledger:
 def __init__(self,state=None):
  self.state=deepcopy(state) if state else dict(entries={},last_s1={},last_failure={})
  self.state.setdefault('held_evidence',{})
  self.state['entries']={k:e for k,e in self.state['entries'].items() if not obsolete(e) and (e['kind']!='confirmed_correct' or proven(e.get('evidence')))}
 def update(self,owner,result,cards,freeze_point=None,change_class='suffix'):
  added=[]
  def add(cid,part,reason,kind,**extra):
   key=json.dumps([owner,cid,part,reason],sort_keys=True)
   if key not in self.state['entries']:
    entry=dict(owner=owner,checkpoint=cid,part=part,reason=reason,kind=kind,**extra);self.state['entries'][key]=entry;added.append(entry)
   elif kind=='confirmed_correct':self.state['entries'][key].update(extra)
  for e in result.get('items',[]):
   cid=e['checkpoint'];proof=e.get('evidence')
   if e['status']=='S3' and proven(proof):
    old=self.state['held_evidence'].get(cid)
    if not proven(old) or proof['held_instructions']>=old['held_instructions']:self.state['held_evidence'][cid]=deepcopy(proof)
    best=self.state['held_evidence'][cid]
    prerequisites=cards[cid].get('contract',{}).get('prerequisites',[])
    relations=list(dict.fromkeys(p.get('required_relation',p.get('text','')) for p in prerequisites))
    reminder='Required before formation: '+'; '.join(relations) if relations else 'formation and hold constraints'
    for entry in self.state['entries'].values():
     if entry['checkpoint']==cid and entry['kind'] in ('excluded','resolved') and entry['part'] in ('cause','Hold','I_form','form','hold','formation'):
      entry.update(kind='resolved',resolution=deepcopy(best),constraint_reminder=reminder)
    add(cid,'paid','held','confirmed_correct',formed_index=e.get('formed_index'),evidence=deepcopy(proof))
   if e['status']=='S2' and e.get('attribution',{}).get('reason')=='state_condition':
    a=e['attribution'];add(cid,'cause',a['reason_category'],'excluded',evidence='counterfactual_not_input_and_observed_state',description='Prerequisite unmet after entering checkpoint → '+a['reason_category']+'; '+a['driver_conditions'])
   if e['status']=='S2' and e.get('attribution',{}).get('confirmed'):
    a=e['attribution'];reason=json.dumps(a.get('removed_indices',[]));add(cid,'Hold',reason,'excluded',evidence='counterfactual_confirmed',description='Clearing input instruction '+reason+' (counterfactually confirmed)')
   key=owner+':'+cid;previous=self.state['last_s1'].get(key);reasons=sorted({v['reason'] for v in e.get('ineffective_advances',[])});reason=json.dumps(reasons)
   if e['status']=='S1':
    count=previous['count']+1 if previous and previous['reason']==reason else 1;self.state['last_s1'][key]=dict(count=count,reason=reason)
    if count>=2:add(cid,'I_form',reason,'include_advance_guard',writer_lines=cards[cid]['contract']['form'])
   else:self.state['last_s1'].pop(key,None)
  # Earlier suffix/repeated-failure rows are not candidate evidence. Policy's
  # stall/shrink/backtrack counters live elsewhere and remain unchanged.
  return added
 def entries(self,owner,kind=None):return [e for e in self.state['entries'].values() if e['owner']==owner and (kind is None or e['kind']==kind)]
 def serialize(self):return deepcopy(self.state)
