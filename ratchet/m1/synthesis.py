"""C4-C8: frozen bit costs, conservative DAG, generated contracts and monitors."""
from pathlib import Path
import collections,json,hashlib,math
from . import io
from .front import norm,kind,refs,const,refname
from .predicates import writer_guards
from ..expressions import condition_expr,signals,sv
from .contracts import generate_contract
from .causes import attach_causes

def ident(value,prefix='c'):return prefix+hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()[:16]
def observable(f,path):
    path=path.split('[')[0]
    while path not in f.symbols and '.' in path:path=path.rsplit('.',1)[0]
    symbol=f.symbols.get(path)
    return symbol is not None and symbol.type.isIntegral and not symbol.parentScope.isProceduralContext

def annotate(f,c):
    e=condition_expr(c);ss=signals(e)
    if not ss or not all(observable(f,s) for s in ss):return None
    # Closest state drivers, not the entire COI, accompany missing conditions.
    drivers=set()
    for s in ss:
        q=[(s,0)];seen=set()
        while q:
            name,d=q.pop()
            if name in seen or d>8:continue
            seen.add(name)
            if f.regkeys(name):drivers.add(name);continue
            parents,_=f.predecessors(name);q.extend((p,d+1) for p in parents)
    return dict(c,id=ident(e),expr=e,driver_registers=sorted(s for s in drivers if observable(f,s)),structural_inference=True)

def canonical_signature(values):return json.dumps(values,sort_keys=True,separators=(',',':'))

def source_probability(guard):
    """D3 1/6 operation type; only exact known operation-source guards.

    csr_save_cause_i is Ibex's trap-save operation boundary (exception source).
    Extra value/index constraints must be resolved, otherwise p_clr stays NA.
    This maps an interface event, never a target-specific card.
    """
    def flatten(e):
        if e['kind']=='all':
            result=[]
            for a in e['args']:result.extend(flatten(a))
            return result
        if e['kind']=='any' and len(e['args'])==1:return flatten(e['args'][0])
        if e['kind']=='const' and e['value']==1:return []
        if e['kind']=='compare' and e['op']=='==':
            a,b=e['left'],e['right']
            if a['kind']=='const' and a['value']==1:a,b=b,a
            if a['kind']=='ref' and b==dict(kind='const',value=1):return [a['path']]
        if e['kind']=='ref':return [e['path']]
        return [None]
    terms=flatten(guard)
    if terms and None not in terms and all(s.rsplit('.',1)[-1]=='csr_save_cause_i' for s in terms):
        return 1/6,dict(operation_type='exception',type_probability='1/6',guard_fraction=1,source='ibex_cs_registers.sv trap-save case label; no additional guard constraint')
    return None,dict(reason='clear guard is not an exact supported ordinary request/response/CSR/exception operation boundary')

def synthesize(f,regs,bin_rows,out,records):
    params=json.loads((io.X/'configs/params.yaml').read_text());byreg={r['reg']:r for r in regs}
    register_sources=collections.defaultdict(list)
    for node,record in f.assignments:
        for s in record['lhs']:register_sources[norm(s)].append((node,record))
    candidates=[];selected_by_bin={};cards={};condition_bank={};bin_specs={};dropped=[]
    for row in bin_rows:
        selected=[]
        for c in row['conditions']:
            reg=byreg.get(norm(c['signal']))
            if not reg or not reg['is_candidate']:continue
            if c['signal'] not in f.regs:continue  # Checkpoints observe state, not its combinational next-state wire.
            annotated=annotate(f,c)
            if not annotated:continue
            cid=annotated['id'];types=reg['types'];clear=[];clear_unknown=[]
            for node,record in register_sources[reg['reg']]:
                reset=any(record['file']+':'+str(record['line'])==v for v in reg['reset_writers'])
                value=const(node.right)
                is_clear='B2' in types and not reset and (value==0 or value==f.reset.get(reg['reg']))
                if not is_clear:continue
                if c['op']=='==' and len(c['values'])==1 and value==c['values'][0]:continue  # This writer preserves the checkpoint.
                guard,gaps=writer_guards(f,node)
                if gaps or not all(observable(f,s) for s in signals(guard)):
                    clear_unknown.append(dict(source=record['file']+':'+str(record['line']),reason=gaps or ['guard contains procedural-only signal']));continue
                p,evidence=source_probability(guard)
                clear.append(dict(id=ident(guard,'g'),expr=guard,source=record['file']+':'+str(record['line']),p_clr=p,evidence=evidence,value=value))
            N=max(1,int(c['values'][0])) if 'B1' in types and len(c['values'])==1 and c['op'] in ('==','>=','>') else 1 if 'B1' not in types else None
            # A B3 guard's exact equality width must be established. Do not
            # assign 0 to an unresolved object constraint.
            bits=0 if 'B3' not in types else None
            D=N;T=1;T_kind='default'
            ps=list({v['id']:v['p_clr'] for v in clear}.values())
            pclr=0 if 'B2' not in types else ps[0] if len(ps)==1 and None not in ps and not clear_unknown else None
            iform=(math.log2(N) if 'B1' in types else 0)+(bits*D if 'B3' in types and bits is not None and D is not None else 0) if N is not None and bits is not None else None
            hold=-T*math.log2(1-pclr) if 'B2' in types and pclr is not None and pclr<1 else 0 if 'B2' not in types else None
            cost=iform+hold if iform is not None and hold is not None else None
            preparation='B2' not in types and 'B1' not in types
            reasons=[]
            if cost is None:reasons.append('unresolved_frozen_cost_inputs')
            if preparation:reasons.append('single_write_preparation_without_B2')
            if cost==0:reasons.append('zero_cost')
            if not row['complete']:reasons.append('incomplete_derivation_downgrade_to_conjunction')
            candidate=dict(bin=row['bin'],checkpoint=cid,register=reg['reg'],signal=c['signal'],op=c['op'],values=c['values'],types=types,N=N,bits=bits,D=D,p_clr=pclr,T=T,T_kind=T_kind,I_form=iform,Hold=hold,Cost=cost,Dom='structural_inference_common_required',hidden_fields=sum(reg[k] for k in ('prog_hidden','obj_hidden','loss_hidden','ctx_hidden')),is_candidate=True,preparation=preparation,selected=False,exclusion_reasons=reasons,clear_guards=clear,clear_guard_gaps=clear_unknown,depth=c['depth'])
            candidates.append(candidate)
            if not reasons:selected.append((candidate,annotated,reg))
        selected.sort(key=lambda x:(-x[0]['Cost'],-x[0]['hidden_fields'],x[0]['checkpoint']))
        for candidate,c,reg in selected[:params['max_local_checkpoints_per_bin']]:
            candidate['selected']=True;cid=candidate['checkpoint']
            if cid not in cards:
                n=candidate['N'];is_count='B1' in reg['types']
                cards[cid]=dict(id=cid,predicate=c,registers=c['driver_registers'] or [c['signal']],types=reg['types'],measure=dict(kind='scalar' if is_count else 'predicate',signal=c['signal'],target=n if is_count else 1,op=c['op']),object=dict(constraints=reg['index_source'],kind='input_index' if 'B3' in reg['types'] else 'none'),dom='structural_inference',hidden={k:bool(reg[k]) for k in ('prog_hidden','obj_hidden','loss_hidden','ctx_hidden')},window=dict(start=cid,end=[],kind='all_direct_downstream_or_target'),contract=generate_contract(f,c,reg,candidate['clear_guards'],register_sources),clear_guards=candidate['clear_guards'],cost={k:candidate[k] for k in ('N','bits','D','p_clr','T','T_kind','I_form','Hold','Cost')},bins=[],global_gate=False)
            cards[cid]['bins'].append(row['bin']);condition_bank[cid]=c
        selected_by_bin[row['bin']]=[v[0]['checkpoint'] for v in selected[:params['max_local_checkpoints_per_bin']]]
        # Use fully expanded alternatives when complete, otherwise preserve the
        # original coverage predicate. Partial derivation is explicitly labeled.
        alternatives=row['alternatives'] if row['alternatives_complete'] and row['alternatives'] else row['sample_alternatives'] or row['alternatives']
        tables=[]
        for alt in alternatives[:8]:
            conditions=[annotate(f,c) for c in alt['conditions']]
            if not conditions or None in conditions or len(conditions)>8:
                dropped.append(dict(bin=row['bin'],alternative=alt['id'],reason='nonmonitorable_condition_or_capacity'));continue
            for c in conditions:condition_bank[c['id']]=c
            tables.append(dict(id=alt['id'],condition_ids=[c['id'] for c in conditions]))
        hit_alternatives=[]
        for alt in row['sample_alternatives']:
            cc=[annotate(f,c) for c in alt['conditions']]
            if cc and None not in cc:
                for c in cc:condition_bank[c['id']]=c
                hit_alternatives.append(dict(id=alt['id'],condition_ids=[c['id'] for c in cc]))
        chain=selected_by_bin[row['bin']]
        category='chain' if chain and row['complete'] else 'same_cycle' if tables else 'level0_only'
        reason='complete_selected_checkpoint' if category=='chain' else 'incomplete_derivation_with_condition_table' if category=='same_cycle' and not row['complete'] else 'no_positive_cost_checkpoint_with_condition_table' if tables else 'no_reliable_checkpoint_or_monitorable_condition_table'
        bin_specs[row['bin']]=dict(id=row['bin'],category=category,chain=chain if category=='chain' else [],alternatives=tables,hit_alternatives=hit_alternatives,derivation_complete=row['complete'],degradation_reason=reason,sigma_required={},fork_checkpoint=None,required_operations=[],forbidden_operations=[],source_gaps=row['implementation_gaps'])
    # No temporal order is invented from reverse traversal depth. Independent
    # checkpoints stay unordered and their windows end at the common target.
    nodes={cid:dict(id=cid,share=len(card['bins']),global_gate=False) for cid,card in cards.items()};edges=[]
    ordered=sorted(nodes,key=lambda k:(-nodes[k]['share'],k));cut=max(1,math.ceil(len(ordered)*params['theta_share_top_fraction']))
    for cid in ordered[:cut]:
        if nodes[cid]['share']>=params['theta_share_min']:nodes[cid]['global_gate']=cards[cid]['global_gate']=True
    for cid,card in cards.items():card['window']['end']=[dict(kind='bin',id=b) for b in sorted(set(card['bins']))]
    dag=dict(nodes=list(nodes.values()),edges=edges,bins={k:v['chain'] for k,v in bin_specs.items()},order_kind='unordered_unless_structurally_proven',topological_order=sorted(nodes),rules_version='v1.2')
    from .presentation import enrich
    enrich(f,condition_bank)
    attach_causes(f,cards,regs)
    (out/'cards').mkdir(exist_ok=True)
    for cid,card in cards.items():io.write_json(out/'cards'/f'{cid}.yaml',card)
    io.write_json(out/'dag.json',dag);io.write_json(out/'conditions.json',condition_bank);io.write_json(out/'bin_specs.json',bin_specs)
    io.write_json(out/'monitorability_gaps.json',dropped)
    fields=['bin','checkpoint','register','signal','op','values','types','N','bits','D','p_clr','T','T_kind','I_form','Hold','Cost','Dom','hidden_fields','preparation','selected','exclusion_reasons']
    io.write_csv(out/'candidates.csv',[{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in candidates],fields)
    io.write_csv(out/'checkpoints.csv',[dict(checkpoint=k,share=v['share'],global_gate=v['global_gate']) for k,v in nodes.items()],['checkpoint','share','global_gate'])
    io.write_csv(out/'bin_class.csv',[dict(bin=k,category=v['category'],checkpoints=json.dumps(v['chain']),alternatives=len(v['alternatives']),derivation_complete=v['derivation_complete'],reason=v['degradation_reason']) for k,v in bin_specs.items()],['bin','category','checkpoints','alternatives','derivation_complete','reason'])
    from .monitor import generate
    generate(f,cards,condition_bank,out/'monitor')
    files=[out/'dag.json',out/'conditions.json',out/'bin_specs.json',out/'monitor/ckpt_mon.sv',out/'monitor/signals.json',*sorted((out/'cards').glob('*.yaml'))]
    io.write_json(out/'runtime_hashes.json',{str(p.relative_to(out)):io.sha(p) for p in files})
    return dict(C4_C8='generated',checkpoints=len(cards),bin_categories=dict(collections.Counter(v['category'] for v in bin_specs.values())),monitorability_gaps=len(dropped))
