"""Cause classification and prerequisite fork regression; zero model calls."""
import unittest
from copy import deepcopy
from tests.test_scheduler import fixture,rows
from ratchet.m2 import diagnose,Attributor,Ledger
from ratchet.m2.render import render
from ratchet.sched import Bundle,Budget,Scheduler
from ratchet.sched.runner import R
def data(answer=False):
 card,spec,conditions=fixture();card['clear_causes']={'1':dict(category='instr_access_fault',branches=[dict(signal='permission_denied',requires_before_formation=True,required_relation='permission_denied = 0')],permission_checks=[])}
 trace=rows([0,4,0]);trace[1]['clear_guards']={'clear':True};trace[1]['clear_input']=dict(index=1,cause=1,interrupt=0);trace[1]['state']['permission_denied']=1
 return card,spec,conditions,trace
class AttributionTests(unittest.TestCase):
 def test_false_replay_and_observed_state(self):
  c,s,co,t=data();d=diagnose(t,s,{'checkpoint':c},co,Attributor(),lambda *a:(False,0),['a','b','c']);e=d['items'][0]
  self.assertEqual(e['attribution']['reason_category'],'instr_access_fault');self.assertEqual(d['action']['freeze_reason'],'prerequisite');self.assertEqual(d['action']['before_index'],1)
 def test_unknown_replay_is_not_state_proof(self):
  c,s,co,t=data();d=diagnose(t,s,{'checkpoint':c},co,Attributor(),lambda *a:(None,0),['a','b','c']);self.assertEqual(d['items'][0]['attribution']['reason'],'unconfirmed')
 def test_missing_probe_is_not_state_proof(self):
  c,s,co,t=data();t[1]['state'].pop('permission_denied');d=diagnose(t,s,{'checkpoint':c},co,Attributor(),lambda *a:(False,0),['a','b','c']);self.assertEqual(d['action']['freeze_reason'],'S2')
 def test_positive_replay_remains_input_attribution(self):
  c,s,co,t=data();d=diagnose(t,s,{'checkpoint':c},co,Attributor(),lambda *a:(True,0),['a','b','c']);self.assertTrue(d['items'][0]['attribution']['confirmed']);self.assertEqual(d['action']['freeze_reason'],'S2')
 def test_cause_ledger_deduplicates_and_renders(self):
  c,s,co,t=data();d=diagnose(t,s,{'checkpoint':c},co,Attributor(),lambda *a:(False,0),['a','b','c']);l=Ledger()
  for _ in range(3):l.update('bin',d,{'checkpoint':c})
  entries=l.entries('bin','excluded');self.assertEqual(len(entries),1);self.assertEqual(entries[0]['reason'],'instr_access_fault');text=render(d,entries,800);self.assertIn('Prerequisite mismatch',text);self.assertNotIn('repeated_failure',text);self.assertNotIn('suffix',text)
 def test_actual_generated_prerequisite_and_disabled_modes(self):
  b=Bundle(R/'artifacts/ibex');c=next(iter(b.cards.values()));cause=c['clear_causes']['1'];self.assertEqual(cause['enum'],'ExcCauseInstrAccessFault');pre=c['contract']['prerequisites'];self.assertTrue(pre);self.assertTrue(any('region_basic_perm_check' in p['text'] for p in pre));self.assertFalse(any('cheriot_' in p['required_relation'] for p in pre))
 def test_freeze_uses_last_archive_strictly_before_formation(self):
  b=Bundle(R/'artifacts/ibex');s=Scheduler(b,budget=Budget(100,3600,100));bid=next(v for v in b.specs if b.specs[v]['chain']);s.records=[dict(source='test',test={'asm':'nop\n'},rows=[])];s.diagnostics[bid]={'action':dict(freeze_reason='prerequisite',before_formation=True,before_index=10,freeze_point=None)}
  s.archives.state['entries']=[dict(id=str(i),source='test',index=i,sigma={},prefix=['nop\n']*(i+1),checkpoint='test') for i in [2,9,10,11]];entry,reason=s.freeze(dict(primary=bid));self.assertEqual(entry['index'],9);s.archives.state['entries']=[];entry,reason=s.freeze(dict(primary=bid));self.assertEqual(entry['index'],-1)
if __name__=='__main__':unittest.main()
