"""Regression checks for the five authorized implementation fixes; zero LLM."""
from ratchet.utils.workspace import Workspace
import unittest
from copy import deepcopy
from tests.test_scheduler import fixture,rows
from ratchet.m2 import diagnose,Attributor
from ratchet.m2.render import render,contract_text
from ratchet.m3.request import assemble
from ratchet.core import count
from ratchet.sched import Bundle
from ratchet.sched.runner import R
class CheckpointDiagnosisTests(unittest.TestCase):
 def test_boot_formation_loss_excluded(self):
  card,spec,conditions=fixture();trace=rows([4,0,0,0]);trace[0]['index']=-1;trace[1]['index']=-1
  d=diagnose(trace,spec,{'checkpoint':card},conditions);self.assertEqual(d['items'][0]['status'],'S0');self.assertNotIn('formed_index',d['items'][0])
 def test_initially_formed_and_reset(self):
  card,spec,conditions=fixture();trace=rows([4,4,4,0]);trace[0]['index']=-1;trace[1]['reset_released']=False
  d=diagnose(trace,spec,{'checkpoint':card},conditions);e=d['items'][0];self.assertEqual(e['status'],'S2');self.assertEqual(e['formed_index'],2);self.assertTrue(e['initially_formed']);self.assertEqual(e['window_start_index'],0)
 def test_text_render_no_window_bin_dump(self):
  card,spec,conditions=fixture();d=diagnose(rows([0,4,0]),spec,{'checkpoint':card},conditions);text=render(d,(),800)
  self.assertIn('Frontier: ',text);self.assertIn('S2',text);self.assertIn('unconfirmed',text);self.assertNotIn('"checkpoint"',text);self.assertIn('1 downstream bins',text);self.assertLessEqual(count(text),800)
 def test_section_caps(self):
  r=assemble({k:' data'*9000 for k in ['primary_card','accounting','segment_slice']},12000)
  for k,n in [('primary_card',1500),('accounting',800),('segment_slice',4000)]:self.assertLessEqual(r['part_tokens'][k],n)
 def test_rider_reservation_protected(self):
  parts={k:' data'*12000 for k in ['primary_card','accounting','ledger','segment_slice','prefix_summary','history']};parts['riders']=' rider'*600
  r=assemble(parts,12000,rider_count=3);self.assertEqual(r['rider_reserved_tokens'],750);self.assertGreaterEqual(r['part_tokens']['riders'],600);self.assertLessEqual(r['total_tokens'],12000)
 def test_rho_prevents_replay(self):
  card,spec,conditions=fixture();trace=rows([0,4,0]);trace[1]['clear_guards']={'clear':True};calls=[]
  at=Attributor(rho=0);d=diagnose(trace,spec,{'checkpoint':card},conditions,at,lambda *args:calls.append(args),['a','b','c']);self.assertEqual(calls,[]);self.assertFalse(d['items'][0]['attribution']['confirmed'])
 def test_real_generated_contract(self):
  bundle=Bundle(R/'artifacts/ibex');self.assertEqual(len(bundle.cards),1);card=next(iter(bundle.cards.values()));s=contract_text(card)
  self.assertIn('MRET',s);self.assertIn('mpp',s);self.assertIn('csr_we_int',s);self.assertIn('interrupt',s);self.assertTrue(card['contract']['forbid'])
 def test_focused_compaction_keeps_downstream_consumption(self):
  from unittest.mock import patch
  from ratchet.sched.trace import read_trace
  trace=rows([4,4,4])
  for row,value in zip(trace,[False,True,False]):row.update(conditions={'checkpoint':True,'downstream':value})
  with patch('ratchet.sched.trace.iter_trace',return_value=iter(trace)):
   compact=read_trace('.',{},compact=True,focus=('checkpoint',[]))
  self.assertEqual([r['cycle'] for r in compact],[0,1,2])
 def test_monitor_and_tracer_clocks_are_distinct(self):
  import json,tempfile
  from pathlib import Path
  from ratchet.sched.trace import read_trace
  with Workspace() as d:
   p=Path(d);(p/'pc_to_primitive.json').write_text(json.dumps({'0000':0,'0004':1}))
   (p/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in [{'cycle':2,'pc':'0000'},{'cycle':3,'pc':'0004'}]))
   (p/'ratchet_monitor.jsonl').write_text(json.dumps(dict(cycle=10,trace_cycle=2,reset_released=True,state={},conditions={},measures={},clear_guards={}))+'\n')
   trace=read_trace(p,dict(asm='nop\nnop\n'));self.assertEqual(trace[0]['index'],0)
 def test_freeze_cut_preserves_balanced_assembler_blocks(self):
  from ratchet.sched.replay import safe_prefix_cut
  lines=['addi x1,x0,1\n','.rept 3\n','nop\n','.endr\n','nop\n']
  self.assertEqual(safe_prefix_cut(lines,3),1);self.assertEqual(safe_prefix_cut(lines,4),4)
 def test_empty_derived_trace_falls_back_to_native_log(self):
  import tempfile
  from pathlib import Path
  from ratchet.sched.trace import execution_rows
  with Workspace() as d:
   p=Path(d);(p/'trace.jsonl').write_text('');(p/'trace_core_00000000.log').write_text('Time Cycle PC Insn\n20 6 00100080 0800006f instruction\n')
   values=list(execution_rows(p));self.assertEqual(len(values),1);self.assertEqual(values[0]['cycle'],6)
if __name__=='__main__':unittest.main()
