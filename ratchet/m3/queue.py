"""Deterministic cohorts, lock matching, explicit contract conflicts."""
from .archives import matching,stable

def overlaps(a,b):
    if isinstance(a,str) or isinstance(b,str):return a==b
    # Required/forbidden operation patterns overlap when shared constraints agree.
    if 'kind' in a and 'kind' in b and a['kind']!=b['kind']:return False
    if 'guard' in a or 'guard' in b:return a.get('guard')==b.get('guard')
    common=set(a)&set(b)
    return bool(common) and all(a[k]==b[k] for k in common)
def conflict(a,b):
    for left,right in ((a,b),(b,a)):
        for required in left.get('required_operations',[]):
            for forbidden in right.get('forbidden_operations',[]):
                if overlaps(required,forbidden):return dict(reason='required_operation_is_forbidden',required=required,forbidden=forbidden)
    return None

def progress_priority(spec,diagnostic):
    if spec['category']=='same_cycle':return (diagnostic or {}).get('conjunction',{}).get('g',0) if (diagnostic or {}).get('conjunction') else 0
    k,m=(diagnostic or {}).get('progress',(0,0));return (k+m+1)/(len(spec['chain'])+1)

def select_queue(specs,diagnostics,archives,cards,remaining,config,crossed=()):
    eligible=[];excluded=[]
    for bid in sorted(remaining):
        spec=specs[bid];diag=diagnostics.get(bid,{})
        if spec['category']=='level0_only':excluded.append(dict(bin=bid,reason=spec['degradation_reason']));continue
        if spec['category']=='same_cycle' and (not config['conjunct'] or not diag.get('conjunction') or not diag['conjunction']['near_miss']):excluded.append(dict(bin=bid,reason='not_a_conjunct_near_miss_or_ablation_off'));continue
        if diag.get('status')=='lock_mismatch':excluded.append(dict(bin=bid,reason='lock_mismatch_requires_fork'));continue
        chain=spec['chain'] or ['Rest:'+bid]
        entry=archives.choose(chain,spec['sigma_required'],bid)
        anchor=entry['checkpoint'] if entry else spec.get('fork_checkpoint')
        sigma=entry['sigma'] if entry else dict(spec['sigma_required'])
        gates=[cards[c] for c in spec['chain'] if cards[c]['global_gate'] and c not in crossed]
        gate_share=max((len(c['bins']) for c in gates),default=0)
        eligible.append(dict(id=bid,spec=spec,entry=entry,anchor=anchor,sigma=sigma,gate_share=gate_share,priority=progress_priority(spec,diag)))
    if not eligible:return None,excluded
    # Cohort-wide summed priority, then stable primary ID. K is deterministic.
    options=[]
    for seed in eligible:
        pool=[];rejections=[]
        for candidate in sorted(eligible,key=lambda x:(-x['gate_share'],-x['priority'],x['id'])):
            same_prefix=(seed['entry'] or {}).get('id')==(candidate['entry'] or {}).get('id')
            shared_anchor=seed['anchor']==candidate['anchor'] and stable(seed['sigma'])==stable(candidate['sigma'])
            if not (same_prefix or shared_anchor) or not matching(seed['sigma'],candidate['spec']['sigma_required']):continue
            if candidate['id']!=seed['id'] and config['escalation']=='single':continue
            issue=next((conflict(candidate['spec'],member['spec']) for member in pool if conflict(candidate['spec'],member['spec'])),None)
            if issue:rejections.append(dict(bin=candidate['id'],**issue));continue
            pool.append(candidate)
        if seed['id'] not in [c['id'] for c in pool]:continue
        options.append(dict(members=pool,gate_share=max((c['gate_share'] for c in pool),default=0),priority=sum(c['priority'] for c in pool),excluded=rejections))
    if not options:return None,excluded
    best=sorted(options,key=lambda o:(-o['gate_share'],-o['priority'],tuple(c['id'] for c in o['members'])))[0]
    members=best['members'];primary=members[0];K=1 if config['escalation']=='single' else config['K'];prompted=members[:K]
    result=dict(id='cohort:'+primary['id']+':'+str(primary['anchor']),primary=primary['id'],riders=[m['id'] for m in prompted[1:]],all_bins=[m['id'] for m in members],freeze_ckpt=primary['anchor'],entry=primary['entry'],sigma=primary['sigma'],priority=best['priority'])
    return result,excluded+best['excluded']
