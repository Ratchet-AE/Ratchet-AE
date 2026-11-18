"""Scheduler with injected model and execution interfaces."""
from pathlib import Path
from copy import deepcopy
import json,random,hashlib,time
from ..core import count,ENC
from ..m2 import diagnose,Ledger,Attributor,render,render_v2
from ..m2.render import contract_text,render_ledger,expression
from ..m3 import Archives,Policy,select_queue,assemble,sanitize
from ..m3.archives import matching
from ..m3.request import prefix_summary
from ..dut_api import DUTAdapter
from .budget import Budget
from .artifacts import Bundle
from ..expressions import evaluate
R=Path(__file__).resolve().parents[1];X=R.parent

def progress(spec,diagnostic):
    if spec['category']=='same_cycle':return (0,(diagnostic.get('conjunction') or {}).get('g',0))
    return tuple(diagnostic.get('progress',(0,0)))
def tuples(value):return tuple(tuples(x) for x in value) if isinstance(value,list) else value

def configuration(name):
    cfg=json.loads((R/'config'/f'{name}.yaml').read_text());params=json.loads((X/'configs/params.yaml').read_text());cfg.update({k:v for k,v in params.items() if k not in cfg});return cfg

class Scheduler:
    def __init__(self,bundle,config='r3_cohort',seed=0,coverage=(),lines=(),budget=None,enable_model_calls=False,dut_adapter=None):
        if isinstance(config,str):config=configuration(config)
        self.dut_adapter=dut_adapter or DUTAdapter();self.enable_model_calls=enable_model_calls;self.bundle=bundle;self.config=deepcopy(config);self.rng=random.Random(seed);self.seed=seed
        self.coverage=set(coverage);self.lines=set(lines);self.initial_coverage=set(coverage);self.remaining=set(bundle.specs)-self.coverage
        self.archives=Archives();self.ledger=Ledger();self.policy=Policy(config);self.policy.state['shrunken']=config['escalation']=='single'
        self.diagnostics={};self.records=[];self.calls=0;self.outputs=[];self.history=[];self.log=[];self.crossed=set();self.cohort=None;self.freeze_override={};self.stop_reason=None
        self.budget=budget or Budget(token_cap=0,wall_seconds=0,global_remaining=0)
        self.attributor=Attributor(config['R_max'],config['rho'],self.budget.wall_seconds)
    def save_archive(self,checkpoint,units,index,rows,owner,source,global_gate=False,key_state=None,sample_row=None):
        cut,validation,failures=self.dut_adapter.check_prefix(units,index+1)
        log=self.archives.state.setdefault('validation_log',[])
        event=dict(source=source,checkpoint=checkpoint,requested_index=index,index=None if cut is None else cut-1,assembly=validation,failed_checks=failures)
        if cut is None or cut!=index+1 or failures:log.append(event)
        if cut is None:return None
        if cut==index+1:
            sample=sample_row or next((r for r in rows if r.get('index',-1)==index),{})
        else:sample=next((r for r in reversed(rows) if 0<=r.get('index',-1)<cut and (sample_row is None or r['cycle']<=sample_row['cycle'])),{})
        state=sample.get('state',{});held=[cid for cid,c in self.bundle.cards.items() if evaluate(c['predicate']['expr'],state) is True]
        actual=checkpoint if cut==index+1 or checkpoint in held else 'Fork:'+checkpoint
        key=key_state if cut==index+1 and key_state is not None else {k:state.get(k) for k in (key_state or state)}
        entry=self.archives.add(actual,sample.get('sigma',{}),key,units[:cut],owner,source,cut-1,global_gate and actual==checkpoint)
        if entry:
            stored=next(e for e in self.archives.state['entries'] if e['id']==entry['id']);stored.update(assembly_validation=validation,held_checkpoints=held,observed_state=state,label_closed=True,original_checkpoint=checkpoint,original_index=index);entry=deepcopy(stored)
        return entry
    def ingest(self,test,result,level,source,replay=None):
        before=set(self.coverage);old_lines=set(self.lines);added_archives=[];added_ledger=[]
        if result.get('status') not in ('ok','trap_storm'):return dict(new_bins=[],new_lines=[],diagnostics={},new_archives=[],ledger_entries=[],status=result.get('status'))
        # Every valid candidate contributes to the entire coverage universe,
        # including targets outside the selected/prompted cohort.
        self.coverage.update(result.get('hits',[]));self.lines.update(result.get('line_hits',[]));self.remaining-=self.coverage
        rows=result.get('rows',[]);units=self.dut_adapter.primitives(test);record=dict(test=deepcopy(test),rows=deepcopy(rows),source=source,level=level)
        self.records.append(record);all_diags={}
        for bid,spec in self.bundle.specs.items():
            diagnostic=diagnose(rows,spec,self.bundle.cards,self.bundle.conditions,self.attributor,replay,units,conjunct=self.config['conjunct'],exemption_hook=self.dut_adapter.exempt_self_induced_exception)
            from .evidence import attach
            attach(diagnostic,result.get('retirements',[]),result.get('evidence_test_id') if 'retirements' in result else None,rows,result.get('evidence_scope','native_trace'))
            self.diagnostics[bid]=diagnostic;all_diags[bid]=diagnostic
            if self.config['ledger']:added_ledger.extend(self.ledger.update(bid,diagnostic,self.bundle.cards,diagnostic['action']['freeze_point'],result.get('change_class','suffix')))
            for item in diagnostic.get('items',[]):
                if 'formed_index' not in item:continue
                cid=item['checkpoint'];card=self.bundle.cards[cid];index=item['formed_index']
                # Snapshots before the user program cannot become prefixes.
                if index<0:continue
                row=next((r for r in rows if r['cycle']==item['formed_cycle']),{})
                key_state={k:row.get('state',{}).get(k) for k in card['registers']}
                if any(v is None for v in key_state.values()):continue
                entry=self.save_archive(cid,units,index,rows,bid,source,card['global_gate'],key_state,row)
                if entry:
                    added_archives.append(entry)
                    if cid in entry.get('held_checkpoints',[]):self.crossed.add(cid)
            conjunction=diagnostic.get('conjunction')
            if spec['category']=='same_cycle' and conjunction and conjunction['near_miss'] and conjunction['index']>=0:
                index=conjunction['index'];row=next((r for r in rows if r['cycle']==conjunction['t_star']),{})
                drivers={s for m in conjunction['missing_conditions'] for s in m['drivers']};state={s:row.get('state',{}).get(s) for s in drivers}
                if not drivers:state={'conditions':row.get('conditions',{})}
                entry=self.save_archive('Rest:'+bid,units,index,rows,bid,source,key_state=state,sample_row=row)
                if entry:added_archives.append(entry)
        return dict(new_bins=sorted(self.coverage-before),new_lines=sorted(self.lines-old_lines),diagnostics=all_diags,new_archives=added_archives,ledger_entries=added_ledger,status='ok')
    def choose(self):
        cfg=dict(self.config)
        if self.policy.state['shrunken']:cfg.update(escalation='single',K=1)
        remaining=self.remaining-set(self.policy.state['excluded'])
        return select_queue(self.bundle.specs,self.diagnostics,self.archives,self.bundle.cards,remaining,cfg,self.crossed)
    def freeze(self,cohort):
        bid=cohort['primary'];spec=self.bundle.specs[bid];diagnostic=self.diagnostics.get(bid)
        entry=self.freeze_override.get(bid) or cohort.get('entry');reason='initial_deepest_matching_archive'
        if diagnostic:
            act=diagnostic['action'];reason=act['freeze_reason']
            if act.get('before_formation'):
                # Last matching archive strictly preceding the formation.
                # No archive means reset, not an ephemeral post-formation cut.
                candidates=[v for v in self.archives.state['entries'] if v['source']==self.records[-1]['source'] and v['index']<act['before_index'] and matching(v['sigma'],spec['sigma_required'])] if self.records else []
                entry=max(candidates,key=lambda v:v['index']) if candidates else None
            elif act['freeze_reason']=='lock':entry=self.archives.choose([spec.get('fork_checkpoint')],{},bid)
            elif self.records and ('before_index' in act or 'at_index' in act):
                record=self.records[-1];index=act.get('before_index',act.get('at_index',-1)+1)
                if index>=0:
                    requested_index=index;index,validation,failures=self.dut_adapter.check_prefix(self.dut_adapter.primitives(record['test']),index)
                    if index is None:index=0
                    rows=[r for r in record['rows'] if r.get('index',-1)<index];row=rows[-1] if rows else {}
                    entry=dict(prefix=self.dut_adapter.primitives(record['test'])[:index],checkpoint=act['freeze_point'] if index==requested_index else None,index=index-1,key_state=row.get('state',{}),sigma=row.get('sigma',{}),id='ephemeral:'+str(index))
            elif act['freeze_point'] is not None:
                chosen=self.archives.choose([act['freeze_point']],spec['sigma_required'],bid)
                if chosen:entry=chosen
        return deepcopy(entry or dict(prefix=[],checkpoint=spec.get('fork_checkpoint'),index=-1,key_state={},sigma={},id='reset')),reason
    def build_request(self,level,cohort=None,entry=None,slice_provider=None):
        card_text=(self.dut_adapter.root/self.dut_adapter.config['card']).read_text();cfg=self.config
        if level=='0':
            grouped={}
            for bid in sorted(self.remaining):grouped.setdefault(bid.rsplit('.',1)[0],[]).append(bid.rsplit('.',1)[-1])
            summary=ENC.decode(ENC.encode(json.dumps(grouped,ensure_ascii=False))[:2000])
            contracts=[contract_text(c) for c in self.bundle.cards.values() if c['global_gate'] and c['id'] not in self.crossed] if cfg['contract'] else []
            contract=ENC.decode(ENC.encode(json.dumps(contracts,ensure_ascii=False))[:cfg['C_contract']]) if contracts else ''
            request=card_text+'\nUncovered groups:\n'+summary+'\n'+(R/'prompts/l0.txt').read_text()+('\nGlobal gate contracts:\n'+contract if contract else '')
            return dict(text=request,part_tokens=dict(primary_card=count(request)-count(contract),global_contract=count(contract)),truncated=[],total_tokens=count(request)),1,cfg['L_max']
        bid=cohort['primary'];spec=self.bundle.specs[bid];diagnostic=self.diagnostics[bid];chain=[sanitize(self.bundle.cards[c],cfg['contract']) for c in spec['chain']]
        maximum=cfg['L_max']-self.dut_adapter.count_instructions(''.join(entry['prefix']))
        N=cfg['N_max'] if maximum<=cfg['L_max']/2 else cfg['N']
        primary='Primary target: '+bid+' ('+spec['category']+')\n'+(R/'prompts/upgrade.txt').read_text()+f' Return exactly {N} candidates, each {cfg["L_min"]}..{maximum} instructions.'
        if cfg['contract']:
            primary+='\nContract: \n'+'\n'.join(contract_text(self.bundle.cards[c]) for c in spec['chain'])
        else:primary+='\nCheckpoint: '+'; '.join(expression(self.bundle.cards[c]['predicate']['expr']) for c in spec['chain'])
        primary+='\nDUT card: \n'+card_text
        diagnostic_text=render(diagnostic,self.ledger.entries(bid),min(800,cfg['D_max'])) if cfg['diagnosis']=='protocol' else render_v2(diagnostic)
        boundary=self.bundle.cards.get(entry['checkpoint'],{}).get('registers',[])
        segment=slice_provider(bid,boundary,diagnostic) if slice_provider else dict(text='',reason='no_tracker_provider',boundary_registers=boundary)
        rider_text=[]
        for b in cohort['riders']:
            rs=self.bundle.specs[b];desc='Secondary target: '+b+' ('+rs['category']+')\n'
            if cfg['contract']:
                for cid in rs['chain']:
                    card=self.bundle.cards[cid];desc+='Hold constraint: '+'; '.join(v.get('text',expression(v.get('guard',v))) for v in card['contract']['forbid'])+'\nFormation target: '+expression(card['predicate']['expr'])+'\n'
            else:desc+='Condition: '+'; '.join(expression(self.bundle.conditions[c]['expr']) for a in rs['alternatives'] for c in a['condition_ids'])
            rider_text.append(ENC.decode(ENC.encode(desc)[:250]))
        parts=dict(primary_card=primary,accounting=diagnostic_text,ledger=render_ledger(self.ledger.entries(bid)) if cfg['ledger'] else '',segment_slice=segment.get('text','') if isinstance(segment,dict) else segment,prefix_summary=prefix_summary(entry,self.bundle.cards,cfg['contract'],self.dut_adapter.count_instructions,self.dut_adapter.key_state_registers),riders='\n\n'.join(rider_text),history=sorted(self.history,key=lambda h:(-h['gain'],h['source']))[:cfg['history_h']])
        if self.policy.state['shrunken']:parts.update(riders='',history='')
        parts=sanitize(parts,cfg['contract']);request=assemble(parts,cfg['B'],rider_count=len(cohort['riders']))
        maximum=cfg['L_max']-self.dut_adapter.count_instructions(''.join(entry['prefix']))
        N=cfg['N_max'] if maximum<=cfg['L_max']/2 else cfg['N']
        return request,N,maximum
    def step(self,caller,executor,slice_provider=None,stop_after_response=False):
        if not getattr(caller,'is_mock',False) and not self.enable_model_calls:raise RuntimeError('zero-call upgrade: only explicit mock caller is enabled; model calls require explicit authorization')
        self.bundle.verify()
        level='0';cohort=None;excluded=[];entry=dict(prefix=[],checkpoint=None,key_state={},sigma={},id='reset',index=-1);reason='level0'
        if self.config['escalation']!='off' and self.policy.state['upgraded'] and not self.policy.state['insert_l0']:
            cohort,excluded=self.choose()
            if cohort:
                entry,reason=self.freeze(cohort)
                if self.config['L_max']-self.dut_adapter.count_instructions(''.join(entry['prefix']))>=self.config['L_min']:level='esc'
                else:excluded.append(dict(bin=cohort['primary'],reason='prefix_leaves_no_minimum_suffix_room'));cohort=None;entry.update(prefix=[],checkpoint=None)
        self.policy.state['insert_l0']=False
        request,N,maximum=self.build_request(level,cohort,entry,slice_provider)
        schema=json.loads((self.dut_adapter.root/self.dut_adapter.config['candidate_schema']).read_text())
        if level=='0':schema=json.loads((self.dut_adapter.root/self.dut_adapter.config['level_zero_schema']).read_text())
        else:
            schema['properties']['candidates'].update(minItems=N,maxItems=N)
            schema['properties']['candidates']['items']['properties']['primary_target']['enum']=[cohort['primary'],*cohort['riders']]
        allowed,stop,estimate=self.budget.reserve(request['text'],json.dumps(schema),self.outputs)
        if not allowed:self.stop_reason=stop;return dict(stopped=stop,model_called=False,reservation=estimate)
        old=progress(self.bundle.specs[cohort['primary']],self.diagnostics[cohort['primary']]) if cohort else (0,0)
        before=set(self.coverage);start=time.monotonic();response=caller(request['text'],schema,N,level,dict(cohort=cohort,maximum=maximum,minimum=self.config['L_min']))
        parsed=response['parsed'];self.calls+=1;used=response.get('tokens',0);self.budget.account(used);self.outputs.append(response.get('output_tokens',0))
        if stop_after_response:
            return dict(stopped='dry_run',level=level,request=request,schema=schema,reservation=estimate,response=response,usage_source='mock' if getattr(caller,'is_mock',False) else 'api',actual_model_calls=0)
        candidates=self.dut_adapter.candidates(parsed,level)
        if len(candidates)!=N:raise ValueError('candidate count mismatch')
        tests=[];gain=0
        for i,candidate in enumerate(candidates):
            length=self.dut_adapter.count_instructions(self.dut_adapter.candidate_fragment(candidate))
            if level=='esc' and candidate.get('primary_target') not in [cohort['primary'],*cohort['riders']]:raise ValueError('candidate target outside prompted cohort')
            if length>maximum or level=='esc' and length<self.config['L_min']:
                tests.append(dict(status='parse_fail',reason='suffix_length',n_units=length));continue
            test=self.dut_adapter.splice_prefix(entry['prefix'],self.dut_adapter.build_stimulus(candidate))
            result=executor(test,dict(level=level,cohort=cohort,candidate=i,reset=True,timeout_s=self.dut_adapter.config['single_test_timeout']))
            summary=self.ingest(test,result,level,f'call{self.calls}:candidate{i}',result.get('replay'))
            if self.config['ledger'] and cohort:summary['ledger_entries']+=self.ledger.update(cohort['id'],self.diagnostics[cohort['primary']],self.bundle.cards,entry['checkpoint'],result.get('change_class','suffix'))
            gain+=len(summary['new_bins']);tests.append(dict(primary_target=candidate.get('primary_target'),**summary))
            self.history.append(dict(source=f'call{self.calls}:{i}',suffix=self.dut_adapter.candidate_fragment(candidate),gain=len(summary['new_bins']),progress=list(progress(self.bundle.specs[cohort['primary']],self.diagnostics[cohort['primary']])) if cohort else [0,0]))
        operation='level0'
        if level=='0':self.policy.tier0(len(self.coverage-before))
        elif cohort:
            new=progress(self.bundle.specs[cohort['primary']],self.diagnostics[cohort['primary']]);operation=self.policy.update(old,new,gain,bool((self.coverage-before)&set(cohort['all_bins'])))
            if operation=='switch_archive':
                if entry.get('id')!='reset':self.archives.reject(cohort['primary'],entry)
                alternative=self.archives.choose([entry['checkpoint']],self.bundle.specs[cohort['primary']]['sigma_required'],cohort['primary'])
                if alternative:self.freeze_override[cohort['primary']]=alternative
                else:operation='previous_checkpoint';self._previous(cohort)
            elif operation=='previous_checkpoint':self._previous(cohort)
            elif operation=='demote':self.policy.state['excluded'].append(cohort['primary'])
        self.cohort=deepcopy(cohort)
        record=dict(config=self.config['name'],level=level,call_idx=self.calls,cohort_id=cohort['id'] if cohort else None,primary_bin=cohort['primary'] if cohort else None,rider_bins=cohort['riders'] if cohort else [],freeze_ckpt=entry['checkpoint'],freeze_reason=reason,prefix_len=len(entry['prefix']),input_tokens=request['part_tokens'],truncated=request['truncated'],candidate_count=N,tests=tests,new_function_bins=sorted(self.coverage-before),new_line_keys=sorted({v for t in tests for v in t.get('new_lines',[])}),queue_exclusions=excluded,policy_action=operation,reservation=estimate,wall_s=time.monotonic()-start,usage_source='mock' if getattr(caller,'is_mock',False) else 'unified_client',simulated_tokens=used if getattr(caller,'is_mock',False) else 0,actual_model_calls=0 if getattr(caller,'is_mock',False) else 1)
        self.log.append(record);return record
    def _previous(self,cohort):
        spec=self.bundle.specs[cohort['primary']];chain=spec['chain'];point=(self.freeze_override.get(cohort['primary']) or cohort.get('entry') or {}).get('checkpoint')
        position=chain.index(point) if point in chain else len(chain)
        previous=self.archives.choose(chain[:position],spec['sigma_required'],cohort['primary'])
        if previous:self.freeze_override[cohort['primary']]=previous
        else:self.freeze_override[cohort['primary']]=dict(prefix=[],checkpoint=spec.get('fork_checkpoint'),index=-1,key_state={},sigma={},id='reset')
    def snapshot(self):
        return dict(version='ratchet',dut=self.dut_adapter.name,artifact_identity=self.bundle.identity,config=deepcopy(self.config),seed=self.seed,rng=self.rng.getstate(),coverage=sorted(self.coverage),initial_coverage=sorted(self.initial_coverage),lines=sorted(self.lines),remaining=sorted(self.remaining),archives=self.archives.serialize(),ledger=self.ledger.serialize(),policy=deepcopy(self.policy.state),diagnostics=deepcopy(self.diagnostics),records=deepcopy(self.records),calls=self.calls,outputs=list(self.outputs),history=deepcopy(self.history),log=deepcopy(self.log),crossed=sorted(self.crossed),cohort=deepcopy(self.cohort),freeze_override=deepcopy(self.freeze_override),budget=self.budget.snapshot(),attribution=dict(elapsed=self.attributor.elapsed,replays=self.attributor.replays,cache=deepcopy(self.attributor.cache)))
    @classmethod
    def restore(cls,bundle,snapshot,config=None,dut_adapter=None):
        if snapshot['artifact_identity']!=bundle.identity:raise ValueError('snapshot M1 identity mismatch')
        cfg=configuration(config) if isinstance(config,str) else deepcopy(config or snapshot['config'])
        if dut_adapter is None and snapshot.get('dut'):
            from ..dut_api import load_dut
            _,dut_adapter=load_dut(snapshot['dut'])
        obj=cls(bundle,cfg,snapshot['seed'],snapshot['coverage'],snapshot['lines'],Budget(**snapshot['budget']),dut_adapter=dut_adapter)
        obj.attributor.deadline-=snapshot['budget']['elapsed_before'];obj.rng.setstate(tuples(snapshot['rng']));obj.initial_coverage=set(snapshot['initial_coverage']);obj.remaining=set(snapshot['remaining']);obj.archives=Archives(snapshot['archives']);obj.ledger=Ledger(snapshot['ledger']);obj.policy=Policy(cfg,deepcopy(snapshot['policy']))
        for key in ('diagnostics','records','calls','outputs','history','log','cohort','freeze_override'):setattr(obj,key,deepcopy(snapshot[key]))
        obj.crossed=set(snapshot['crossed']);obj.attributor.elapsed=snapshot['attribution']['elapsed'];obj.attributor.replays=snapshot['attribution']['replays'];obj.attributor.cache=deepcopy(snapshot['attribution']['cache'])
        return obj
    def write(self,out):
        out=Path(out);out.mkdir(parents=True,exist_ok=True)
        (out/'config_snapshot.yaml').write_text(json.dumps(self.config,indent=2)+'\n');(out/'budget.json').write_text(json.dumps(dict(self.budget.snapshot(),usage_source='mock',actual_model_calls=0),indent=2)+'\n')
        (out/'snapshot.json').write_text(json.dumps(self.snapshot(),indent=2)+'\n');(out/'calls.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.log))
