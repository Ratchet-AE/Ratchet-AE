"""Check reconciliation and ledger rendering."""
import unittest
from copy import deepcopy
from ratchet.m2 import Ledger,diagnose
from ratchet.m2.render import render,render_ledger,expression
from ratchet.m2.ledger import proven
from ratchet.sched import Bundle
from ratchet.sched.runner import R
from ratchet.sched.evidence import attach
from ratchet.expressions import evaluate,signals
from tests.test_scheduler import fixture,rows
class LedgerTests(unittest.TestCase):
 def test_unproved_confirmations_removed(self):
  entries={'a':dict(owner='x',checkpoint='c',part='retry',reason='suffix',kind='excluded'),'b':dict(owner='x',checkpoint='c',part='retry',reason='other',kind='excluded',evidence='repeated_failure'),'c':dict(owner='x',checkpoint='c',part='paid',reason='held',kind='confirmed_correct')}
  self.assertFalse(Ledger(dict(entries=entries,last_s1={},last_failure={})).state['entries'])
 def test_s3_resolves_old_cause_once_with_proof(self):
  card,spec,c=fixture();ledger=Ledger();ledger.state['entries']={'old':dict(owner='bin',checkpoint='checkpoint',part='cause',reason='fault',kind='excluded')};d=diagnose(rows([0,4,4]),spec,{'checkpoint':card},c);d['items'][0]['evidence']=dict(test_id='synthetic:test',held_instructions=2)
  ledger.update('bin',d,{'checkpoint':card});entries=ledger.entries('bin');self.assertEqual(ledger.state['entries']['old']['kind'],'resolved');text=render_ledger(entries);self.assertIn('verified effective',text);self.assertIn('synthetic:test',text);self.assertIn('held 2  instructions',text);self.assertNotIn('excluded: checkpoint',text)
 def test_unmeasured_s3_does_not_claim_correctness(self):
  card,spec,c=fixture();l=Ledger();d=diagnose(rows([0,4]),spec,{'checkpoint':card},c);l.update('bin',d,{'checkpoint':card});self.assertFalse(l.entries('bin','confirmed_correct'))
 def test_proof_is_not_truncated_away(self):
  e=dict(owner='x',checkpoint='c',kind='confirmed_correct',reason='held',evidence=dict(test_id='very_long_test_name'*20,held_instructions=3));text=render_ledger([e],20);self.assertNotIn('confirmed correct: c',text)
 def test_real_enum_and_classifier_predicate(self):
  b=Bundle(R/'artifacts/ibex');c=next(c for c in b.conditions.values() if c['signal'].endswith('id_instr_category') and c['values']==[20]);p=c['presentation'];self.assertIn('InstrCategoryCSRIllegal',expression(p['expression']));guard=p['decision_paths'][0]['predicate'];ss=signals(guard);state={s:int(s.endswith(('.instr_valid_i','.illegal_csr_insn_i'))) for s in ss};self.assertTrue(evaluate(guard,state));state[next(s for s in ss if s.endswith('.illegal_csr_priv'))]=1;self.assertFalse(evaluate(guard,state));self.assertTrue(any(e['source'].endswith('ibex_cs_registers.sv:403') for e in p['rtl_equations']))
 def test_conjunction_uses_predicates_not_register_values(self):
  b=Bundle(R/'artifacts/ibex');c=next(c for c in b.conditions.values() if c['signal'].endswith('id_instr_category') and c['values']==[20]);d=dict(status='accounted',bin='pending',items=[],frontier=None,chain=[],action=dict(freeze_point=None,freeze_reason='Rest'),conjunction=dict(satisfied=0,total=1,index=0,missing_conditions=[dict(expression=c['expr'],presentation=c['presentation'],drivers={'RAW_SECRET':123})]));text=render(d,D_max=1500);self.assertIn('InstrCategoryCSRIllegal',text);self.assertIn('Decision condition: ',text);self.assertIn('ibex_cs_registers.sv:403',text);self.assertNotIn('RAW_SECRET',text);self.assertNotIn('id_instr_category == 20',text)
 def test_primary_window_visible_even_when_held(self):
  card,spec,c=fixture();spec=dict(spec,id='pending_CSR');d=diagnose(rows([0,4,4]),spec,{'checkpoint':card},c);text=render(d);self.assertIn('primary target window pending_CSR',text);self.assertIn(': S3',text);self.assertNotIn('ALU',text)
 def test_exact_window_retirement_count(self):
  d=dict(bin='target',items=[dict(checkpoint='c',formed_cycle=2,window_end=3)]);attach(d,[dict(cycle=i,held=['c']) for i in range(1,5)],'synthetic:retirements',[dict(cycle=4)],scope='synthetic_unit');self.assertEqual(d['items'][0]['evidence']['held_instructions'],2);self.assertTrue(proven(d['items'][0]['evidence']))
 def test_s4_does_not_resolve_as_s3(self):
  card,spec,c=fixture();l=Ledger(dict(entries={'old':dict(owner='bin',checkpoint='checkpoint',part='Hold',reason='clear',kind='excluded')},last_s1={},last_failure={}));d=diagnose(rows([0,4,4,0],2),spec,{'checkpoint':card},c);d['items'][0]['evidence']=dict(test_id='synthetic:s4',held_instructions=1);l.update('bin',d,{'checkpoint':card});self.assertEqual(l.state['entries']['old']['kind'],'excluded')
if __name__=='__main__':unittest.main()
