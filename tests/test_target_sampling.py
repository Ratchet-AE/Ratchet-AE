"""Check target sampling and request constraints."""
import unittest
from tests.test_scheduler import fixture,rows
from ratchet.m2 import diagnose
from ratchet.m2.render import contract_text
from ratchet.m3.request import assemble,prefix_summary,compile_failure_stop
class TargetSamplingTests(unittest.TestCase):
 def test_target_before_own_trap(self):
  c,s,d=fixture();t=rows([0,4,4,0],2);t[-1]['clear_input']={'index':2,'cause':2}
  self.assertEqual(diagnose(t,s,{'checkpoint':c},d)['items'][0]['status'],'S4')
 def test_target_sample_on_loss_edge(self):
  c,s,d=fixture();t=rows([0,4,0],2);t[-1]['clear_input']={'index':2,'cause':2}
  self.assertEqual(diagnose(t,s,{'checkpoint':c},d)['items'][0]['status'],'S4')
 def test_trap_before_target(self):
  c,s,d=fixture();t=rows([0,4,0,4],3);t[2]['clear_input']={'index':1,'cause':2}
  self.assertEqual(diagnose(t,s,{'checkpoint':c},d)['items'][0]['status'],'S2')
 def test_contract_qualification(self):
  c,_,_=fixture();self.assertIn('a trap raised by the target instruction itself does not count as a violation',contract_text(c))
 def test_prefix_cap_and_record(self):
  r=assemble({'prefix_summary':' data'*5000});self.assertLessEqual(r['part_tokens']['prefix_summary'],1500);self.assertIn('prefix_summary',r['truncated'])
 def test_prefix_last_twenty(self):
  text=prefix_summary({'prefix':[f'addi x1,x0,{i}\n' for i in range(40)],'key_state':{},'checkpoint':None},{})
  self.assertIn('addi x1,x0,20',text);self.assertNotIn('addi x1,x0,19',text);self.assertIn('addi x1,x0,39',text)
 def test_compile_minimum(self):
  self.assertFalse(compile_failure_stop(['compile_fail']*7));self.assertFalse(compile_failure_stop(['compile_fail']*4+['ok']*4));self.assertTrue(compile_failure_stop(['compile_fail']*5+['ok']*3))
