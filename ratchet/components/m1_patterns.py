"""Four structural v0 patterns recognized from assignment/condition/case ASTs."""
from collections import defaultdict,deque
from ratchet.slicing.tracker import kind,parents,identifiers
import re,math
def number(text):
    text=text.strip().replace('_','')
    if text in ("'0","'1"):return int(text[-1])
    m=re.fullmatch(r"(?:\d+)?'([bdho])([0-9a-f]+)",text,re.I)
    try:return int(m[2],{'b':2,'d':10,'h':16,'o':8}[m[1].lower()]) if m else int(text,0)
    except (ValueError,TypeError):return None
def path_to(graph,start,target):
    queue=deque([(start,[start])]);seen=set()
    while queue:
        x,path=queue.popleft()
        if x==target:return path
        if x in seen:continue
        seen.add(x)
        queue.extend((y,path+[y]) for y in sorted(graph.get(x,())) if y not in seen)
    return []
def build_catalog(tracker):
    writes=defaultdict(list)
    for s in tracker.statements:
        if s.sequential:
            for n in s.lhs:writes[(s.module,n)].append(s)
    result={}
    for key,statements in writes.items():
        module,reg=key;patterns=[]
        sequential=list(statements);expanded=list(statements);seen_ids={s.id for s in statements};front={n for s in sequential for n in s.rhs if n!=reg}
        for _ in range(4):
            new=[]
            for s in tracker.statements:
                if s.module==module and not s.sequential and s.id not in seen_ids and set(s.lhs)&front:
                    new.append(s);seen_ids.add(s.id)
            if not new:break
            expanded+=new;front={n for s in new for n in s.rhs if n!=reg}
        statements=expanded
        inc=[];comparisons=[];bus=[];transitions=defaultdict(set);reset=None
        for s in statements:
            n=tracker.syntax[s.id];rhs=n.right;k=kind(rhs)
            if k in ('AddExpression','SubtractExpression') and reg in identifiers(rhs):inc.append(s)
            if s.case_expr and reg in re.findall(r'\b\w+\b',s.case_expr):
                target=str(rhs).strip()
                if re.fullmatch(r'[A-Za-z_]\w*(?:::\w+)?',target):
                    for label in s.case_labels:transitions[label].add(target)
            if any(re.search(r'rst|reset',c,re.I) for c in s.conditions) and re.fullmatch(r'[A-Za-z_]\w*(?:::\w+)?',str(rhs).strip()):reset=str(rhs).strip()
            if any(re.search(r'addr|write|wr_en|we\b|psel|a_write|qe\b',c,re.I) for c in s.conditions):bus.append(s)
        # Comparisons are found in AST expressions anywhere in the same module,
        # not just the update's own condition (counter targets are often fanout).
        for s in tracker.statements:
            if s.module!=module or reg not in s.signals:continue
            def visit(n):
                if kind(n) in ('EqualityExpression','InequalityExpression','LessThanExpression','LessThanEqualExpression','GreaterThanExpression','GreaterThanEqualExpression') and reg in identifiers(n):
                    other=n.right if reg in identifiers(n.left) else n.left
                    comparisons.append(dict(text=str(n),other=str(other),threshold=number(str(other))))
            tracker.syntax[s.id].visit(visit)
            for p in parents(tracker.syntax[s.id]):
                if kind(p)=='ConditionalStatement':p.predicate.visit(visit)
                if kind(p) in ('ModuleDeclaration','InterfaceDeclaration'):break
        if inc and comparisons:
            c=next((c for c in comparisons if c['threshold'] is not None and c['threshold']>0),comparisons[0]);threshold=c['threshold'];th=threshold if threshold else c['other']
            patterns.append(dict(pattern='counter_threshold',register=list(key),threshold=th,checkpoints=[dict(op='ge',register=list(key),value=math.ceil(threshold*f/4)) for f in (1,2,3,4)] if threshold else [dict(op='ge_fraction',register=list(key),threshold_register=th,fraction=f/4) for f in (1,2,3,4)],progress='value / threshold',regression='decrease_or_clear'))
        if inc and any(any(re.search(r'==|!=',c) and not re.search(r'rst|reset',c,re.I) for c in s.conditions) for s in inc) and any(number(str(tracker.syntax[s.id].right))==0 for s in statements):
            patterns.append(dict(pattern='history_accumulation',register=list(key),checkpoints=[dict(op='ge',register=list(key),value=i) for i in (1,2,3)],progress='confidence_level',regression='decrease'))
        if transitions:
            states=set(transitions)|{x for a in transitions.values() for x in a};start=reset if reset in states else sorted(states)[0]
            paths=[path_to(transitions,start,t) for t in sorted(states)];path=max(paths,key=len,default=[])
            if path:patterns.append(dict(pattern='fsm_deep_state',register=list(key),reset=start,graph={k:sorted(v) for k,v in transitions.items()},checkpoints=[dict(op='eq_enum',register=list(key),value=s,path=path,position=i) for i,s in enumerate(path)],progress='furthest_path_state',regression='earlier_path_state'))
        effective=[s for s in statements if not any(re.search(r'rst|reset',c,re.I) for c in s.conditions) and not (not s.conditions and set(s.rhs)&{r for w in sequential for r in w.rhs})]
        if bus and effective and all(s in bus for s in effective):
            # Require fanout enable usage; mere bus-driven data is not a gate.
            used=any(s.module==module and any(re.search(r'\b'+re.escape(reg)+r'\b',c) for c in s.conditions) for s in tracker.statements)
            if used:
                comparison=next((c for c in comparisons if '==' in c['text']),None)
                gate_value=(comparison['threshold'] if comparison['threshold'] is not None else comparison['other']) if comparison else 1
                patterns.append(dict(pattern='configuration_gate',register=list(key),checkpoints=[dict(op='target_value',register=list(key),value=gate_value)],progress='satisfied_gate_count',regression='field_rewrite',requires_target_value=False))
        if patterns:
            indices=sorted({m[1] for s in sequential if (m:=re.search(re.escape(reg)+r'\[(\d+)\]',str(tracker.syntax[s.id].left)))})
            if indices:
                import copy
                expanded=[]
                for index in indices:
                    for p in patterns:
                        p=copy.deepcopy(p);p['register']=[module,reg+f'[{index}]']
                        for cp in p['checkpoints']:cp['register']=p['register']
                        expanded.append(p)
                patterns=expanded
            result[key]=patterns
    if hasattr(tracker,'active_registers'):result={k:v for k,v in result.items() if k in tracker.active_registers}
    return result
def match_target(tracker,target,catalog=None):
    from .m1_slice import sequential_dependencies
    deps=sequential_dependencies(tracker,target['seeds']);catalog=build_catalog(tracker) if catalog is None else catalog
    import copy,json
    patterns=[copy.deepcopy(p) for reg in deps['registers'] for p in catalog.get(tuple(reg),[])]
    # A target-specific FSM endpoint is chosen from actual bin enum values/name;
    # otherwise retain the catalog path and explicitly identify its provenance.
    for p in patterns:
        if p['pattern']=='fsm_deep_state':
            text=json.dumps(target.get('bins',[]));states=set(p['graph'])|{v for values in p['graph'].values() for v in values}
            desired=[s for s in states if re.search(r'\b'+re.escape(s.split('::')[-1])+r'\b',text)]
            if target['kind']=='line':
                for st in tracker.statements:
                    if st.module==p['register'][0] and st.line<=max(target['lines']) and st.end_line>=min(target['lines']):desired+=st.case_labels
            paths=[path_to(p['graph'],p['reset'],s) for s in desired];path=max(paths,key=len,default=[])
            if path:p['checkpoints']=[dict(op='eq_enum',register=p['register'],value=s,path=path,position=i) for i,s in enumerate(path)]
            p['endpoint_binding']='target_state' if path else 'catalog_path_without_resolved_target_endpoint'
    patterns=[p for p in patterns if p['pattern']!='fsm_deep_state' or p.get('endpoint_binding')=='target_state']
    return dict(target_id=target['id'],matched=bool(patterns),patterns=patterns,checkpoint_count=sum(len(p['checkpoints']) for p in patterns),dependencies=deps,unmatched=not patterns)
class Refinement:
    def __init__(self):self.failures=defaultdict(int);self.successes=defaultdict(int)
    def observe(self,chain,index,passed):
        key=(tuple(str(x) for x in chain),index)
        counters=self.successes if passed else self.failures;counters[key]+=1
        if counters[key]<5:return chain
        counters[key]=0;chain=[dict(x) for x in chain]
        if passed and index+1<len(chain):return chain[:index]+chain[index+1:]
        if not passed and index>0:
            a,b=chain[index-1],chain[index]
            if a.get('op')==b.get('op')=='ge' and isinstance(a.get('value'),(int,float)) and b['value']>a['value']:
                mid=dict(b,value=(a['value']+b['value'])/2);return chain[:index]+[mid]+chain[index:]
        return chain
