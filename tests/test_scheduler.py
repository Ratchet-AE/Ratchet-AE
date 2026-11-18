"""Tests for scheduler state, queue selection, and budgets."""
from ratchet.utils.workspace import Workspace
import unittest,json,tempfile,shutil,sys
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from types import SimpleNamespace
from ratchet.sched import Bundle,Budget,Scheduler
from ratchet.sched.runner import R,configuration,progress
from ratchet.sched.mock import MockModel,MockExecutor
from ratchet.sched.adapters import TrackerSlice
from ratchet.sched.trace import read_trace
from ratchet.m2 import diagnose,Attributor,Ledger,render
from ratchet.m3 import Archives,Policy,conflict,select_queue,assemble
from ratchet.lib.compose import compose
from ratchet.core import count
from ratchet.expressions import evaluate
EVIDENCE={}

def fixture():
    expr=dict(kind='compare',left=dict(kind='ref',path='fixture.count'),op='>=',right=dict(kind='const',value=4))
    condition=dict(id='checkpoint',expr=expr,driver_registers=['fixture.count'])
    card=dict(id='checkpoint',predicate=condition,measure=dict(kind='scalar',signal='fixture.count',target=4),hidden=dict(prog_hidden=True,obj_hidden=True,loss_hidden=True,ctx_hidden=False),registers=['fixture.count'],types=['B1','B2'],global_gate=False,bins=['bin'],window=dict(start='checkpoint',end=[dict(kind='bin',id='bin')]),clear_guards=[dict(id='clear')],contract=dict(form=[dict(guard='advance && address == object',writer_lines=['fixture.sv:10'])],forbid=[dict(kind='EXCEPTION')]))
    spec=dict(id='bin',category='chain',chain=['checkpoint'],alternatives=[],hit_alternatives=[],sigma_required={},fork_checkpoint=None)
    return card,spec,{'checkpoint':condition}
def rows(values,hits_at=None):
    return [dict(cycle=i,index=i,state={'fixture.count':v},conditions={},measures={},clear_guards={},hits=['bin'] if i==hits_at else [],events=[],sigma={}) for i,v in enumerate(values)]
class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.bundle=Bundle(R/'artifacts/ibex')
    def test_01_runtime_artifact_hashes(self):
        self.bundle.verify()
        with Workspace() as d:
            p=Path(d)/'bundle';shutil.copytree(self.bundle.path,p,ignore=shutil.ignore_patterns('m1_open_log.txt'))
            target=p/'dag.json';target.write_text(target.read_text()+' ')
            with self.assertRaises(ValueError):Bundle(p)
        EVIDENCE['01']=dict(status='passed',runtime_hash_count=len(self.bundle.hashes),mutation_rejected=True)
    def test_02_states_and_lock(self):
        card,spec,conditions=fixture();cases={'S0':rows([0,0]),'S1':rows([0,2,2]),'S2':rows([0,4,0]),'S3':rows([0,4,4]),'S4':rows([0,4,4,0],2)}
        for expected,trace in cases.items():self.assertEqual(diagnose(trace,spec,{'checkpoint':card},conditions)['items'][0]['status'],expected)
        bad=dict(spec,sigma_required={'mode':3});locked=diagnose(rows([0,4]),bad,{'checkpoint':card},conditions);self.assertEqual(locked['status'],'lock_mismatch');self.assertEqual(locked['items'],[]);self.assertEqual(locked['action']['freeze_reason'],'lock')
        EVIDENCE['02']=dict(status='passed',states=list(cases),S4_not_S2=True,lock_checked=True)
    def test_03_attribution(self):
        card,spec,conditions=fixture();trace=rows([0,4,4,0]);trace[2]['clear_guards']={'clear':True};calls=[]
        def replay(indices,event,remaining):
            self.assertTrue(event['preserve_timing']);self.assertTrue(event['exclude_from_coverage']);self.assertEqual(event['stop_cycle'],3);calls.append(indices);return 2 in indices,.001
        at=Attributor();result=diagnose(trace,spec,{'checkpoint':card},conditions,at,replay,['a','b','c','d']);e=result['items'][0]['attribution'];self.assertTrue(e['confirmed']);self.assertEqual(calls,[[2]])
        again=diagnose(trace,spec,{'checkpoint':card},conditions,at,replay,['a','b','c','d']);self.assertTrue(again['items'][0]['attribution']['confirmed']);self.assertEqual(len(calls),1)
        empty=deepcopy(trace);empty[2]['clear_guards']={};b=Attributor();v=diagnose(empty,spec,{'checkpoint':card},conditions,b,replay,['a','b','c','d']);self.assertTrue(v['items'][0]['attribution']['confirmed']);self.assertLessEqual(b.replays,6)
        multiple=deepcopy(trace);multiple[1]['clear_guards']={'clear':True};before=len(calls);d=diagnose(multiple,spec,{'checkpoint':card},conditions,Attributor(),replay,['a','b','c','d']);self.assertEqual(len(calls),before);self.assertFalse(d['items'][0]['attribution']['confirmed'])
        EVIDENCE['03']=dict(status='passed',static_unique_replays=1,cache_reused=True,bisection_replays=b.replays,multiple_static_not_bisected=True)
    def test_05_ledger_rules(self):
        card,spec,conditions=fixture();trace=rows([0,2]);trace[1]['events']=[dict(checkpoint='checkpoint',advance=True,object_ok=False,reason='wrong_index',actual=1,required=0)]
        d=diagnose(trace,spec,{'checkpoint':card},conditions);ledger=Ledger();ledger.update('bin',d,{'checkpoint':card},'checkpoint','wrong_object');ledger.update('bin',d,{'checkpoint':card},'checkpoint','wrong_object')
        kinds={e['kind'] for e in ledger.entries('bin')};self.assertIn('include_advance_guard',kinds);self.assertNotIn('excluded',kinds)
        paid=diagnose(rows([0,4]),spec,{'checkpoint':card},conditions);paid['items'][0]['evidence']=dict(test_id='synthetic:paid',held_instructions=1);ledger.update('paid',paid,{'checkpoint':card});self.assertTrue(ledger.entries('paid','confirmed_correct'))
        lost=diagnose(rows([0,4,0]),spec,{'checkpoint':card},conditions);lost['items'][0]['attribution']=dict(confirmed=True,removed_indices=[2]);ledger.update('confirmed',lost,{'checkpoint':card});self.assertEqual(ledger.entries('confirmed','excluded')[0]['evidence'],'counterfactual_confirmed')
        self.assertEqual(Ledger(ledger.serialize()).serialize(),ledger.serialize());EVIDENCE['05']=dict(status='passed',four_rules=True,serializable=True)
    def test_06_queue_conflict(self):
        cfg=configuration('r3_cohort');specs={k:dict(id=k,category='chain',chain=['cp'],sigma_required={},fork_checkpoint=None,required_operations=[],forbidden_operations=[],degradation_reason='') for k in ['a','b']};specs['a']['required_operations']=[dict(kind='EXCEPTION')];specs['b']['forbidden_operations']=[dict(kind='EXCEPTION')]
        cards={'cp':dict(global_gate=True,bins=['a','b'])};archives=Archives();entry=archives.add('cp',{},dict(q=1),['prefix'],'a','fixture');diags={k:dict(progress=(0,0)) for k in specs}
        q,excluded=select_queue(specs,diags,archives,cards,set(specs),cfg);self.assertEqual(len(q['all_bins']),1);self.assertTrue(any(e['reason']=='required_operation_is_forbidden' for e in excluded))
        specs['b']['forbidden_operations']=[];q,_=select_queue(specs,diags,archives,cards,set(specs),cfg);self.assertEqual(len(q['all_bins']),2);self.assertEqual(archives.choose(['cp'],{},'b')['owner'],'a')
        EVIDENCE['06']=dict(status='passed',conflict_excluded=True,matching_cohort=True,archive_shared=True)
    def test_07_shrink_and_backtrack(self):
        p=Policy(configuration('r3_cohort'));actions=[p.update((0,0),(0,0),0) for _ in range(11)]
        self.assertEqual([x for x in actions if x in ['shrink','switch_archive','previous_checkpoint','demote']],['shrink','switch_archive','previous_checkpoint','demote']);self.assertTrue(p.state['insert_l0'])
        a=Archives();first=a.add('cp',{},dict(q=1),['one'],'t','one');second=a.add('cp',{},dict(q=2),['two'],'t','two');a.reject('t',first);self.assertEqual(a.choose(['cp'],{},'t')['id'],second['id'])
        EVIDENCE['07']=dict(status='passed',actions=actions)
    def test_08_progress(self):
        self.assertGreater((2,0),(1,.99));p=Policy(configuration('r3_cohort'));self.assertEqual(p.update((1,.2),(1,.3),0),'progress');self.assertEqual(p.update((0,.5),(0,.75),0),'progress');self.assertEqual(p.update((0,0),(0,0),1,True),'progress')
        EVIDENCE['08']=dict(status='passed',lexicographic=True,conjunction=True,cohort_new_hit=True)
    def test_09_budgeted_native_requests(self):
        cfg=configuration('r3_cohort');s=Scheduler(self.bundle,cfg,budget=Budget(1000000,14400,1000000));native=R/'artifacts/selftest/monitor_equivalence/monitored';test=json.loads((native/'dsl.json').read_text());trace=read_trace(native,test);s.ingest(test,dict(status='ok',hits=[],rows=trace),'0','native_selftest')
        slicer=TrackerSlice(self.bundle);reports=[]
        selected=[bid for bid,spec in self.bundle.specs.items() if spec['category']=='chain'][:3];self.assertEqual(len(selected),3)
        for bid in selected:
            cohort=dict(primary=bid,riders=[],all_bins=[bid],id=bid);entry=dict(prefix=[],checkpoint=None,key_state={});request,N,maximum=s.build_request('esc',cohort,entry,slicer)
            self.assertLessEqual(request['total_tokens'],12000);self.assertLessEqual(request['part_tokens']['accounting'],1500);self.assertNotIn('"Cost"',request['text']);self.assertNotIn('"p_clr"',request['text']);reports.append(dict(bin=bid,part_tokens=request['part_tokens'],total_tokens=request['total_tokens'],truncated=request['truncated']))
        huge=assemble({k:(' data'*20000) for k in ['primary_card','accounting','ledger','segment_slice','prefix_summary','riders','history']},12000);self.assertLessEqual(huge['total_tokens'],12000);self.assertEqual(huge['truncated'][:3],['history','riders','prefix_summary'])
        EVIDENCE['09']=dict(status='passed',requests=reports,reverse_truncation=True)
    def test_11_all_candidates_count(self):
        s=Scheduler(self.bundle,budget=Budget(1000000,14400,1000000));outside=next(k for k,v in self.bundle.specs.items() if v['category']=='level0_only');model=MockModel();executor=MockExecutor(self.bundle,outside_hit=outside)
        for _ in range(4):s.step(model,executor)
        self.assertIn(outside,s.coverage);self.assertNotIn(outside,s.remaining);self.assertTrue(any(r['level']=='esc' for r in s.log));self.assertIn(outside,s.diagnostics)
        self.assertGreater(executor.calls,model.calls);EVIDENCE['11']=dict(status='passed',outside_target_counted=outside,all_candidates=executor.calls)
    def test_12_snapshot_branch(self):
        s=Scheduler(self.bundle,budget=Budget(1000000,14400,1000000));m=MockModel();e=MockExecutor(self.bundle)
        for _ in range(2):s.step(m,e)
        snap=json.loads(json.dumps(s.snapshot()));restored=Scheduler.restore(self.bundle,snap);again=json.loads(json.dumps(restored.snapshot()))
        for key in snap:
            if key=='budget':
                self.assertGreaterEqual(again[key]['elapsed_before'],snap[key]['elapsed_before']);self.assertLess(again[key]['elapsed_before']-snap[key]['elapsed_before'],1)
                for f in ('token_cap','wall_seconds','global_remaining','spent'):self.assertEqual(again[key][f],snap[key][f])
            else:self.assertEqual(again[key],snap[key],key)
        branch=Scheduler.restore(self.bundle,snap,'r3_single');self.assertEqual(branch.coverage,s.coverage);self.assertEqual(branch.ledger.serialize(),s.ledger.serialize());self.assertEqual(branch.config['escalation'],'single')
        a=Archives()
        for i in range(3):self.assertIsNotNone(a.add('cp',{},dict(q=i),[i],'owner','fixture'))
        self.assertIsNone(a.add('cp',{},dict(q=4),[4],'owner','fixture'))
        EVIDENCE['12']=dict(status='passed',state_keys=list(snap),branch_config='r3_single',max_three=True)
    def test_13_reservation_no_request(self):
        s=Scheduler(self.bundle,budget=Budget(1,14400,1000000));model=MockModel();result=s.step(model,MockExecutor(self.bundle));self.assertEqual(result['stopped'],'token_cap');self.assertEqual(model.calls,0)
        b=Budget(1000000,14400,1);allowed,why,_=b.reserve('request','{}',[]);self.assertFalse(allowed);self.assertEqual(why,'global_token_cap')
        # Check the authoritative client too, patched only to isolated fixtures.
        from ratchet.llm import client
        import time
        with Workspace() as d:
            root=Path(d);(root/'configs').mkdir();(root/'configs/accounting.yaml').write_text('stage: 3.1\nglobal_token_cap: 1850000\nper_run_token_cap: 200000\nper_run_wall_seconds: 3600\nreservation_gate: true\n')
            run=root/'run';run.mkdir();(run/'budget.json').write_text(json.dumps(dict(raw_tokens_accounted=199999,start_unix=time.time())));schema=root/'schema.json';schema.write_text('{}')
            with patch.object(client,'X',root),patch('ratchet.llm.api_client.call') as launch:
                with self.assertRaises(client.BudgetExhausted):client.call_llm(run,'blocked','gen','test',schema)
                launch.assert_not_called()
        EVIDENCE['13']=dict(status='passed',scheduler_refused=True,unified_client_refused_before_subprocess=True)
