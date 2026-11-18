"""Render deterministic accounting and baseline diagnosis text."""
from ..core import count,ENC,compact

def truncate(text,budget):return ENC.decode(ENC.encode(text)[:budget])
def render_v2(result):
    """Render baseline diagnosis text without the reconciliation protocol."""
    first=result.get('frontier');peak=result['items'][first]['peak'] if first is not None and result.get('items') else None
    return compact(dict(frontier=first if first is not None else len(result.get('items',[])),progress_peak=peak),result['items'][first].get('attribution') if first is not None and result.get('items') else None)

def expression(e):
    if isinstance(e,str):return e
    if not isinstance(e,dict):return str(e)
    k=e.get('kind')
    if k=='ref':return '.'.join(e['path'].split('.')[-2:])
    if k=='const':return e.get('display_name',str(e['value']))
    if k in ('all','any'):return (' and ' if k=='all' else ' or ').join(expression(x) for x in e['args']) or 'true'
    if k=='compare':return expression(e['left'])+' '+e['op']+' '+(str(e.get('display_values',e['values'])) if 'values' in e else expression(e['right']))
    if k=='not':return 'not ('+expression(e['arg'])+')'
    if k=='cast':return expression(e['arg'])
    if k=='select':return expression(e['arg'])+'['+expression(e['index'])+(' +: '+str(e['width']) if e.get('width',1)>1 else '')+']'
    if k=='ternary':return expression(e['condition'])+' ? '+expression(e['yes'])+' : '+expression(e['no'])
    return k or 'unknown expression'

def contract_text(card):
    c=card.get('contract',{});lines=['Checkpoint '+card['id']+': '+expression(card['predicate'].get('expr',card['predicate']))]
    for label,key in [('Formation','form'),('Forbidden within window','forbid'),('Prerequisite','prerequisites')]:
        entries=c.get(key,[])
        if not entries:lines.append(label+': no additional static conditions');continue
        for e in entries:
            text=e.get('text') or expression(e.get('guard',e.get('predicate',e)))
            source=e.get('source')
            path=e.get('operation') or next((p['operation'] for p in c.get('formation_paths',[]) for step in p['steps'] if step.get('source')==source),None)
            item_label=label+(' (path '+path+')' if key=='form' and path else '')
            if key=='forbid' and text.startswith('Forbidden within window '):text=text.removeprefix('Forbidden within window ')
            lines.append(item_label+': '+text+(' ['+source+']' if source else ''))
    if c.get('forbid'):lines.append('Constraint: no trap may occur before the target is hit; a trap raised by the target instruction itself does not count as a violation.')
    lines.append('Hold window: from formation until consumption by '+str(len(card.get('window',{}).get('end',[])))+' downstream bins of this checkpoint; loss after consumption does not count as a violation.')
    return '\n'.join(lines)

def render_ledger(entries,budget=1500):
    from .ledger import proven,obsolete
    lines=[];resolved=set()
    for e in sorted(entries,key=lambda e:(0 if e['kind']=='resolved' else 1,e.get('checkpoint') or '',e.get('reason',''))):
        if obsolete(e):continue
        cid=str(e.get('checkpoint') or 'Rest')
        if e['kind']=='resolved':
            if cid in resolved or not proven(e.get('resolution')):continue
            resolved.add(cid);proof=e['resolution'];line='Constraint reminder: '+cid+'; '+e['constraint_reminder']+' (verified effective); test '+proof['test_id']+', held '+str(proof['held_instructions'])+'  instructions'
        elif e['kind']=='confirmed_correct':
            if not proven(e.get('evidence')):continue
            proof=e['evidence'];line='confirmed correct: '+cid+'; test '+proof['test_id']+', held '+str(proof['held_instructions'])+'  instructions; target window '+proof.get('target',e['owner'])
        else:
            label='excluded' if e['kind']=='excluded' else 'add advance guard';line=label+': '+cid+'; '+str(e.get('description',e.get('reason','')))+'; evidence='+str(e.get('evidence',''))
        # Never truncate a correctness assertion away from its evidence.
        if count('\n'.join(lines+[line]))<=budget:lines.append(line)
    return '\n'.join(lines) if lines else 'Excluded: none; confirmed correct: no entries with evidence.'

def render(result,ledger_entries=(),D_max=1500):
    if result['status']=='lock_mismatch':
        return truncate('Precondition: locked signature mismatch\nRequired configuration: '+'; '.join(k+'='+str(v) for k,v in result['sigma_required'].items())+'\nAction: return to the fork before locking',D_max)
    first=result.get('frontier');e=result['items'][first] if first is not None else result['items'][-1] if result.get('items') else None
    lines=['Precondition: locked signature matches','Frontier: '+(e['checkpoint'] if e else 'Rest (all chain checkpoints satisfied)')]
    if e:
        lines.append('Reconciliation (primary target window '+result['bin']+'): '+e['status']+'; '+('initially formed; the window starts at user instruction 0' if e.get('initially_formed') else 'computed in the user program observation window'))
        if e['hidden'].get('prog_hidden'):lines.append('Measure: peak '+str(e['peak'])+'/'+str(e['target']))
        else:lines.append('Measure: this field is visible; report only formation and loss events')
        lines.append('Formation: '+('not formed' if 'formed_index' not in e else 'instruction '+str(e['formed_index'])+', cycle '+str(e['formed_cycle'])))
        if e['status']=='S2':
            a=e.get('attribution',{});lines.append('Loss: instruction '+str(e['loss_index'])+', cycle '+str(e['loss_cycle']))
            for v in ([] if a.get('reason')=='state_condition' else a.get('matched_inputs',[])):
                cause=v.get('cause') or {}
                lines.append('Clearing input: instruction '+str(v['index'])+': '+v.get('input','unknown input').strip()+('; PC='+cause['pc']+', cause='+str(cause.get('cause'))+', interrupt='+str(cause.get('interrupt')) if cause.get('pc') else ''))
            if a.get('reason')=='state_condition':
                lines.append('Cause category: '+a['reason_category']);lines.append(a['explanation']);lines.append('Prerequisites to satisfy first: '+'; '.join(a['required_prerequisites']))
            elif not a.get('matched_inputs'):lines.append('Clearing input: not uniquely matched statically; search by bounded-window counterfactual replay')
            lines.append('Counterfactual: '+('confirmed' if a.get('confirmed') else 'unconfirmed')+'; '+a.get('reason','no callback')+'; replays: '+str(a.get('replays',0))+'  times')
        for v in e.get('ineffective_advances',[])[:3]:lines.append('Ineffective advance: instruction '+str(v.get('index'))+'; '+str(v.get('reason')))
        lines.append('Window end: '+str(len(e['window'].get('end',[])))+' downstream bins')
    if result.get('conjunction'):
        c=result['conjunction'];lines.append('Conjunction progress: '+str(c['satisfied'])+'/'+str(c['total'])+'; closest instruction '+str(c['index']))
        for m in c['missing_conditions'][:3]:
            p=m.get('presentation',{});lines.append('Missing condition: '+expression(p.get('expression',m['expression'])))
            paths=p.get('decision_paths',[])
            for d in paths[:3]:lines.append('Decision condition: '+expression(d['predicate'])+' ['+d['source']+']')
            if not paths:lines.append('Decision condition: M1 alternatives did not resolve a complete RTL decision path')
            for d in p.get('rtl_equations',[])[:2]:lines.append('RTL condition: '+d['text']+' ['+d['source']+']')
    constraints=[]
    for p in result.get('prior_window_constraints',[]):
        for v in p.get('forbid',[]):constraints.append(v.get('text') or expression(v.get('guard',v)))
    lines.append('Constraint: '+'; '.join(constraints) if constraints else 'Constraint: follow the target card formation and hold contract')
    act=result['action']
    ledger_budget=max(0,min(D_max//3,D_max-count('\n'.join(lines))-100))
    if ledger_budget>=60:lines.append(render_ledger(ledger_entries,ledger_budget))
    lines.append('Action: '+('Prerequisite mismatch (B4): return to the last archive before formation, or reset if none exists' if act.get('before_formation') else act['freeze_reason'])+'; freeze point '+str(act['freeze_point']))
    return truncate('\n'.join(lines),D_max)
