"""M1 phase C build with fail-closed static-inference acceptance gate."""
import sys,os
OPEN=[];X=None;allowed_rand=set()
def audit(event,args):
    if event!='open' or not isinstance(args[0],(str,bytes)):return
    p=os.fsdecode(args[0]);OPEN.append(p)
    dynamic=('/analysis_funnel/attempts/','/uvmb_fail/','/case_hpdcache/traj/','/case_hpdcache/llm_exp/runs/')
    if any(v in p for v in dynamic) or os.path.basename(p) in ('pred.csv','bins.csv','func_hits.json','ckpt.csv') or ('/runs/' in p and p not in allowed_rand):raise RuntimeError('M1 blindness violation '+p)
from pathlib import Path
import json,csv,hashlib,collections,random,datetime
from . import io
from ..paths import RUNS_DIR
X=io.X
from .front import Front,norm,syntax_signals
from .necessity import Necessity
from .gaps import gap_report

def aggregate(front,records,observed):
    rr={}
    for r in records:
        if not r['seq']:continue
        for sig in r['lhs']:
            key=norm(sig);row=rr.setdefault(key,dict(dut=front.c['dut'],reg=key,index_dims=[],types=set(),writer_lines=set(),clear_guards=[],index_source=[],sampled_by_cov=False,prog_hidden=0,obj_hidden=0,loss_hidden=0,ctx_hidden=0,is_candidate=False,reset_writers=[]))
            row['sampled_by_cov']|=r['observed'];row['writer_lines'].add(r['file']+':'+str(r['line']));row['index_source'].extend(r['index_sources'])
            tt=set(r['types'])&{'B1','B2','B3','B4'}
            if r['reset_only']:
                row['reset_writers'].append(r['file']+':'+str(r['line']));tt.discard('B2')
            row['types'].update(tt)
            if 'B2' in tt:row['clear_guards'].append(dict(guards=r['guards'],file=r['file'],line=r['line'],rhs=r['text']))
    for row in rr.values():
        row['prog_hidden']=int('B1' in row['types'] and not row['sampled_by_cov']);row['obj_hidden']=int('B3' in row['types']);row['loss_hidden']=int('B2' in row['types']);row['ctx_hidden']=int('B4' in row['types'] and not row['sampled_by_cov']);row['is_candidate']=bool(row['types'] and any(row[k] for k in ('prog_hidden','obj_hidden','loss_hidden','ctx_hidden')));row['types']=sorted(row['types']);row['writer_lines']=sorted(row['writer_lines'])
    return list(rr.values())

def main(dut, base_cov, audit_open_log=None):
    if audit_open_log is not None:
        sys.addaudithook(audit)
    global allowed_rand
    for d in ('ibex','es'):
        for seed in range(3):allowed_rand.add(str((Path(base_cov)/f'seed{seed}'/'func_bins.csv').resolve()))
    if dut!='ibex':raise ValueError('Unsupported DUT')
    out=RUNS_DIR/dut/'m1';out.mkdir(parents=True,exist_ok=False)
    rule_root=Path(os.environ.get('RATCHET_RULES_ROOT', X/'configs'));rules=rule_root/'rules';freeze=json.loads((rules/'FREEZE.json').read_text());assert freeze['rules_version']=='v1.2'
    for p,h in freeze['sha256'].items():assert io.sha(rule_root/p)==h,p
    try:
        cfg=io.config(dut);io.write_json(out/'static_config.json',cfg)
        points,cpp=io.line_points(dut)
        f=Front(cfg)
        maps=json.loads((X/'analysis_state/seed_map.json').read_text()).get(dut,{}) if dut!='hpdcache' else {}
        sampling=json.loads((X/'duts/ibex/cov/sampling_points.json').read_text()) if dut=='ibex' else {}
        observed=set()
        if dut=='ibex':
            for expr in sampling.values():
                observed|=syntax_signals(expr,cfg['seed_base'],f.all_nodes)
                for observer in f.sample_observers:observed|=syntax_signals(expr,observer,f.all_nodes)
        elif dut=='es':
            for entry in maps.values():
                if len(entry.get('resolved_seeds',[]))==1:observed.update(entry['resolved_seeds'])
        # Raw sampled scalar aliases remain raw observations; arithmetic and
        # comparisons are never promoted to raw visibility.
        from .front import strip,kind,refname
        queue=list(observed)
        while queue:
            signal=queue.pop();source=None
            if signal in f.portexpr and kind(strip(f.portexpr[signal])) in ('NamedValue','HierarchicalValue','MemberAccess'):source=refname(strip(f.portexpr[signal]))
            elif len(f.outports.get(signal,[]))==1:source=f.outports[signal][0]
            elif len(f.ass.get(signal,[]))==1:
                node,_=f.ass[signal][0]
                if kind(strip(node.right)) in ('NamedValue','HierarchicalValue','MemberAccess'):source=refname(strip(node.right))
            if source and source not in observed:observed.add(source);queue.append(source)
        records=f.classify(observed);byfile=collections.defaultdict(list);controls={(str(Path(r['file']).resolve()),r['line']):r for r in f.controls}
        for rec in records:byfile[str(Path(rec['file']).resolve())].append(rec)
        classified=[];rng=random.Random(0)
        for p in points:
            matches=[r for r in byfile[p['file']] if r['line']<=p['line']<=r['end']]
            if matches:
                exact=[r for r in matches if r['line']==p['line']];chosen=min(exact or matches,key=lambda r:r['end']-r['line'])
                primary=chosen['primary'];secondary=[x for x in chosen['types'] if x!=primary];reason=json.dumps(chosen['proof'],ensure_ascii=False);target=';'.join(chosen['lhs'])
            elif (p['file'],p['line']) in controls:primary='V';secondary=[];reason='AST branch/case selection';target=''
            else:primary='V';secondary=[];reason='Coverage branch/block point has no assignment at that source line; classification pending sample audit';target=''
            classified.append(dict(dut=dut,cov_point=p['cov_point'],file=p['file'],line=p['line'],target_sig=target,primary=primary,secondary=';'.join(secondary),reason=reason))
        io.write_csv(out/'line_class.csv',classified,['dut','cov_point','file','line','target_sig','primary','secondary','reason'])
        regs=aggregate(f,records,observed)
        serial=[]
        for r in regs:
            rr=dict(r)
            for k in ('types','writer_lines','clear_guards','index_source','index_dims'):rr[k]=json.dumps(rr[k],ensure_ascii=False)
            serial.append(rr)
        io.write_csv(out/'reg_class.csv',serial,['dut','reg','index_dims','types','writer_lines','clear_guards','index_source','sampled_by_cov','prog_hidden','obj_hidden','loss_hidden','ctx_hidden','is_candidate'])
        examples=[]
        for cls in ('V','B1','B2','B3','B4','D'):
            eligible=[r for r in classified if r['primary']==cls]
            for r in rng.sample(eligible,min(10,len(eligible))):
                lines=Path(r['file']).read_text().splitlines();line=int(r['line']);examples.append(dict(r,rtl_snippet='\n'.join(f'{i+1}: {lines[i]}' for i in range(max(0,line-3),min(len(lines),line+2))),review='pending manual audit'))
        io.write_json(out/'line_class_audit_cases.json',examples)
        io.write_json(out/'register_details.json',regs)
        targets=io.target_bins(dut, base_cov)
        cov=None
        if dut=='ibex':
            from tb.ibex.cov.model import model
            cov=model(X/'third_party/ibex')
        elif dut=='es':
            from duts.es.cov.model import full_definition_model
            from common.tlul.regmap import RegisterMap
            cov=full_definition_model(X/'third_party/opentitan',RegisterMap(X/'third_party/opentitan','entropy_src'))
        unknown_bins=[];bin_rows=[]
        for target in targets:
            solver=Necessity(f);start=solver.bin_start(dut,target,cov,sampling,maps);conditions=solver.propagate(start)
            row=dict(dut=dut,bin=target['bin_id'],conditions=conditions,sample_alternatives=[dict(id='s'+str(i),conditions=[dict(signal=a,op=o,values=list(v)) for a,o,v in sorted(branch)]) for i,branch in enumerate(start.branches) if branch],alternatives=solver.alternatives,alternatives_complete=solver.alternatives_complete,conditional_conditions=solver.conditional_conditions,or_expression_count=solver.or_count,dom_unknown=[v for v in solver.events if v['dom_kind']=='dom_unknown'],implementation_gaps=[v for v in solver.events if v['dom_kind']=='unresolved_implementation'],complete=not any(v['dom_kind']=='unresolved_implementation' for v in solver.events) and solver.alternatives_complete)
            bin_rows.append(row)
            if any(v['dom_kind']=='dom_unknown' for v in solver.events):unknown_bins.append(dict(bin=target['bin_id'],reasons=[v for v in solver.events if v['dom_kind']=='dom_unknown']))
        with (out/'bin_conditions.jsonl').open('w') as stream:
            for row in bin_rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        ratio=len(unknown_bins)/len(targets) if targets else 0
        status=dict(dut=dut,stage='C',C1='generated_pending_sample_audit',C2='generated_pending_checks',C3='generated',target_bins=len(targets),implementation_gap_bins=sum(bool(r['implementation_gaps']) for r in bin_rows),dom_unknown_bins=len(unknown_bins),dom_unknown_ratio=ratio,rule_freeze_sha256=io.sha(rules/'FREEZE.json'),compiled_metadata_sources=cpp,generator_calls=0,simulations=0)
        gaps=gap_report(bin_rows)
        io.write_json(out/'implementation_gaps.json',gaps)
        status.update(implementation_gap_ratio=gaps['target_ratio'],or_expression_bins=sum(bool(r['or_expression_count']) for r in bin_rows),alternative_count_distribution=dict(collections.Counter(str(len(r['alternatives'])) for r in bin_rows)),alternative_table_complete_bins=sum(bool(r['alternatives']) and r['alternatives_complete'] for r in bin_rows),no_checkpoint_and_no_table_gate='not evaluated: C4 not executed',rule_parameters_changed=False)
        status.update(status='C1_C3_ready_with_reported_gaps',quantity_gates=False)
        from .synthesis import synthesize
        result=synthesize(f,regs,bin_rows,out,records)
        status.update(result);io.write_json(out/'build_status.json',status)
        print(json.dumps({k:v for k,v in status.items() if k!='compiled_metadata_sources'},ensure_ascii=False),flush=True)
        return 0
    except BaseException as e:
        io.write_json(out/'build_error.json',dict(error=repr(e),stage='C',dut=dut,generator_calls=0,simulations=0));raise
    finally:
        if audit_open_log is not None:
            Path(audit_open_log).write_text('\n'.join(OPEN)+'\n')
