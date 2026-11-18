"""M2: locked, window-aware S0-S4 accounting and disjunctive conjunctions."""
from copy import deepcopy
from ..expressions import evaluate,read

def truth(condition,row):
    v=row.get('conditions',{}).get(condition['id'])
    return bool(v) if v is not None else evaluate(condition['expr'],row.get('state',{}))

def conjunction(trace,spec,conditions):
    best=None
    for row in trace:
        for alternative in spec.get('alternatives',[]):
            ids=alternative['condition_ids']
            if not ids:continue
            values={cid:truth(conditions[cid],row) for cid in ids}
            satisfied=sum(v is True for v in values.values());missing=[cid for cid in ids if values[cid] is not True]
            candidate=dict(g=satisfied/len(ids),satisfied=satisfied,total=len(ids),alternative_id=alternative['id'],t_star=row['cycle'],index=row.get('index',-1),missing_conditions=[dict(id=cid,unknown=values[cid] is None,expression=conditions[cid]['expr'],presentation=conditions[cid].get('presentation',{}),drivers={s:read(row.get('state',{}),s) for s in conditions[cid]['driver_registers']}) for cid in missing],near_miss=len(missing)<=1)
            # Stable ties: earliest cycle, then serialized alternative order.
            if best is None or candidate['g']>best['g']:best=candidate
    return best

def target_at(row,spec,conditions):
    if spec['id'] in row.get('hits',[]):return True
    alternatives=spec.get('hit_alternatives',[])
    return any(all(truth(conditions[c],row) is True for c in a['condition_ids']) for a in alternatives)

def action(result):
    if result['status']=='lock_mismatch':return dict(freeze_point=result.get('fork_checkpoint'),freeze_reason='lock',before_index=result.get('lock_index',0),prompt_parts=['required_configuration'])
    first=result.get('frontier')
    if first is None:return dict(freeze_point=result['chain'][-1] if result['chain'] else None,freeze_reason='Rest',prompt_parts=['conjunct_accounting'])
    entry=result['items'][first];state=entry['status'];previous=next((e['checkpoint'] for e in reversed(result['items'][:first]) if e['status']=='S3'),None)
    if state=='S0':return dict(freeze_point=previous,freeze_reason='S0',prompt_parts=['segment_slice','formation_contract'])
    if state=='S1':return dict(freeze_point=entry['checkpoint'],freeze_reason='S1',at_index=entry['peak_index'],prompt_parts=['ineffective_advances','object_constraints'])
    if state=='S2' and entry.get('attribution',{}).get('requires_before_formation'):
        return dict(freeze_point=previous,freeze_reason='prerequisite',before_formation=True,before_index=entry['formed_index'],reason_category=entry['attribution']['reason_category'],required_prerequisites=entry['attribution']['required_prerequisites'],prompt_parts=['required_configuration'])
    if state=='S2':return dict(freeze_point=entry['checkpoint'],freeze_reason='S2',before_index=entry['loss_index'],prompt_parts=['confirmed_clear_reason','window_forbid'])
    raise ValueError(state)

def diagnose(trace,spec,cards,conditions,attributor=None,replay=None,inputs=None,conjunct=True,exemption_hook=None):
    trace=sorted((r for r in trace if r.get('index',-1)>=0 and r.get('reset_released',True)),key=lambda r:r['cycle'])
    required=spec.get('sigma_required',{})
    # Locked configuration is read at the branch/start, never at a later trap.
    observed=trace[0].get('sigma',trace[0].get('state',{})) if trace else {}
    if any(observed.get(k)!=v for k,v in required.items()):
        result=dict(status='lock_mismatch',sigma_required=required,sigma_observed={k:observed.get(k) for k in required},fork_checkpoint=spec.get('fork_checkpoint'),lock_index=trace[0].get('index',0) if trace else 0,chain=spec['chain'],items=[],frontier=None,bin=spec['id'])
        result['action']=action(result);return result
    items=[]
    for cid in spec['chain']:
        card=cards[cid];target=max(1,card['measure']['target']);samples=[]
        for row in trace:
            d=row.get('measures',{}).get(cid)
            valid=truth(card['predicate'],row)
            if d is None:
                d=read(row.get('state',{}),card['measure']['signal']) if card['measure']['kind']=='scalar' else int(valid is True)
            samples.append(dict(row=row,valid=valid,progress=max(0,min(target,d)) if d is not None else 0))
        peak=max(samples,key=lambda r:r['progress']) if samples else dict(progress=0,row=dict(index=-1,cycle=-1))
        formed=next((i for i,s in enumerate(samples) if s['valid'] is True),None)
        e=dict(checkpoint=cid,status='S0' if peak['progress']==0 else 'S1',peak=peak['progress'],target=target,peak_index=peak['row'].get('index',-1),normalized_peak=peak['progress']/target,ineffective_advances=[],hidden=card['hidden'],window=deepcopy(card['window']),window_closed=False)
        if formed is not None:
            start=samples[formed]['row'];e.update(formed_cycle=start['cycle'],formed_index=start.get('index',-1),initially_formed=formed==0,window_start_index=0 if formed==0 else start.get('index',-1))
            end=None
            downstream=[v['id'] for v in card['window']['end'] if v['kind']=='checkpoint']
            for i in range(formed,len(samples)):
                row=samples[i]['row']
                consumed=(all(truth(cards[d]['predicate'],row) is True for d in downstream) if downstream else False) or target_at(row,spec,conditions)
                if consumed:end=i;break
            loss=next((i for i in range(formed+1,len(samples)) if samples[i]['valid'] is False),None)
            # Decode consumption closes this target's window before its own
            # trap. Only a loss strictly before target sampling is destructive.
            consumed_before_loss=end is not None and (loss is None or end<=loss)
            if end is not None:e['target_sample_cycle']=samples[end]['row']['cycle']
            if loss is not None and consumed_before_loss:
                clear=samples[loss]['row'].get('clear_input',{})
                e['target_trap_exempt']=bool(exemption_hook(clear,samples[end]['row'])) if exemption_hook else False
            if loss is not None and not consumed_before_loss:
                r=samples[loss]['row'];e.update(status='S2',loss_cycle=r['cycle'],loss_index=r.get('cause_index',r.get('index',-1)),window_start=start['cycle'],previous=target,current=samples[loss]['progress'])
                e['attribution']=attributor.confirm(trace,card,e,inputs or [],replay) if attributor else dict(confirmed=False,reason='unconfirmed_no_replay',replays=0)
            elif end is not None:
                e.update(status='S4' if loss is not None and loss>=end else 'S3',window_closed=True,window_end=samples[end]['row']['cycle'])
            else:e['status']='S3'  # Held through the observed suffix; window remains open.
        if e['status']=='S1':
            for row in trace:
                for event in row.get('events',[]):
                    if event.get('checkpoint')==cid and event.get('advance') and event.get('object_ok') is False:e['ineffective_advances'].append(dict(index=event.get('index',row.get('index',-1)),reason=event.get('reason','object_constraint_failed'),source=event.get('source'),actual=event.get('actual'),required=event.get('required')))
        items.append(e)
    frontier=next((i for i,e in enumerate(items) if e['status'] in ('S0','S1','S2')),None)
    paid=frontier if frontier is not None else len(items)
    progress=items[frontier]['normalized_peak'] if frontier is not None else 1.0
    conj=conjunction(trace,spec,conditions) if conjunct and (spec['category']=='same_cycle' or frontier is None) else None
    constraints=[dict(checkpoint=e['checkpoint'],window=e['window'],forbid=cards[e['checkpoint']]['contract']['forbid']) for e in items[:paid] if e['status']=='S3']
    result=dict(status='accounted',bin=spec['id'],chain=spec['chain'],items=items,frontier=frontier,progress=(paid,progress),conjunction=conj,prior_window_constraints=constraints,sigma_required=required,sigma_observed={k:observed.get(k) for k in required},fork_checkpoint=spec.get('fork_checkpoint'))
    result['action']=action(result);return result
