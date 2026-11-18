"""Derive cause, writer, and configuration dependencies from RTL evidence."""
from collections import deque
import re
from .front import const,strip,kind,refs,norm,contains,span
from .predicates import writer_guards,ast_expr
from ..expressions import signals

def assignments(f,s):
    return [(n,r) for a in sorted(f.aliases(s)) for n,r in f.ass.get(a,[])]

def cone(f,roots,typed):
    queue=deque((s,0) for s in sorted(roots));seen=set();rows={};terminal=set()
    while queue:
        s,depth=queue.popleft()
        if s in seen or depth>40:continue
        seen.add(s);aa=assignments(f,s)
        if any(r['sequential'] for n,r in aa):
            nonconstant=[n for n,r in aa if const(n.right) is None]
            transparent=('err' in s.lower() or 'fault' in s.lower()) and 'B4' not in typed.get(norm(s),{}).get('types',[]) and bool(nonconstant) and all(kind(strip(n.right)) in ('NamedValue','MemberAccess','HierarchicalValue') and s not in refs(n.right) for n in nonconstant)
            if not transparent:terminal.add(s);continue
        deps=set()
        if s in f.portexpr:deps.update(refs(f.portexpr[s]))
        deps.update(f.outports.get(s,[]))
        for n,r in aa:
            deps.update(refs(n.right));key=(r['file'],r['line'],r['text'])
            rows[key]=dict(signal=s,source=r['file']+':'+str(r['line']),text=' '.join(r['text'].split()),rhs_kind=kind(strip(n.right)),constant=const(n.right),depth=depth)
        if not deps:
            more,_=f.predecessors(s);deps.update(more)
        queue.extend((v,depth+1) for v in sorted(deps) if v!=s)
    return seen,terminal,list(rows.values())

def derive_causes(f,card,registers):
    # Restrict to the checkpoint's physical core, excluding replicated cores.
    parent=card['registers'][0].rsplit('.',2)[0]
    typed={r['reg']:r for r in registers};result={}
    for node,row in f.assignments:
        rhs=strip(node.right);symbol=getattr(rhs,'symbol',None);name=getattr(symbol,'name','')
        value=const(rhs)
        if value is None or 'Cause' not in name or not any(s.startswith(parent+'.') and 'cause' in s.rsplit('.',1)[-1].lower() for s in row['lhs']):continue
        # Select the priority bit of the enclosing one-hot case, not unrelated
        # FSM, reset or valid guards. Follow its asserted writers one layer.
        roots=set()
        for cs,sel,vals in f.cases_by_buffer[span(node)[0]]:
            if contains(cs,span(node)) and const(sel)==1:
                for v in vals:roots.update(refs(v))
        if not roots:continue
        asserted=set()
        for root in roots:
            for n,r in assignments(f,root):
                if const(n.right)==1:
                    g,_=writer_guards(f,n)
                    # Conditions local to the asserted assignment (rather than
                    # the outer pipeline FSM) carry the actual exception input.
                    local=[(cs,cc,neg) for cs,cc,neg in f.conds_by_buffer[span(n)[0]] if contains(cs,span(n))]
                    if local:
                        cs,cc,neg=min(local,key=lambda v:v[0][2]-v[0][1])
                        for c in cc:asserted.update(refs(c))
        seen,terminal,evidence=cone(f,asserted or roots,typed)
        b4=sorted(s for s in terminal if 'B4' in typed.get(norm(s),{}).get('types',[]))
        category=re.sub(r'(?<!^)(?=[A-Z])','_',name.split('Cause',1)[1]).lower()
        # Active OR equations in this slice expose the error source branches.
        # Keep the shallowest multi-input error equation and its next two
        # driver layers. Full evidence is retained separately for auditing.
        equations=[v for v in evidence if ('err' in v['signal'].rsplit('.',1)[-1].lower() or 'fault' in v['signal'].rsplit('.',1)[-1].lower()) and v['rhs_kind'] not in ('NamedValue','MemberAccess','HierarchicalValue') and v['constant'] is None]
        equations.sort(key=lambda v:(v['depth'],len(v['text']),v['source']))
        compact=[]
        for v in equations:
            if v['text'] not in [x['text'] for x in compact]:compact.append(v)
            if len(compact)>=5:break
        probes=set(asserted or roots)
        for v in compact:probes.add(v['signal'])
        # The entire scalar error cone and typed B4 storage are sampled. Arrays
        # remain represented by their scalar storage cells and RTL equations.
        probes.update(s for s in seen if 'err' in s.rsplit('.',1)[-1].lower())
        probes.update(b4)
        text='; '.join(v['text']+' ['+v['source']+']' for v in compact)
        result[str(value)]=dict(cause=value,category=category,enum=name,source=row['file']+':'+str(row['line']),roots=sorted(asserted or roots),driver_conditions=text,driver_equations=compact,b4_registers=b4,probe_signals=sorted(probes),evidence=evidence)
    return result


def signal_constant(f,s,seen=None):
    seen=set(seen or ())
    if s in seen:return None
    seen.add(s)
    def value(n):
        n=strip(n);v=const(n)
        if v is not None:return v
        if kind(n) in ('NamedValue','MemberAccess','HierarchicalValue'):
            from .front import refname
            return signal_constant(f,refname(n),seen)
        if kind(n)=='BinaryOp':
            a=value(n.left);b=value(n.right);op=str(n.op).split('.')[-1]
            if op in ('BinaryAnd','LogicalAnd') and (a==0 or b==0):return 0
            if a is not None and b is not None:
                if op in ('Equality','CaseEquality'):return int(a==b)
                if op in ('Inequality','CaseInequality'):return int(a!=b)
                if op in ('BinaryAnd','LogicalAnd'):return a&b
                if op in ('BinaryOr','LogicalOr'):return a|b
        if kind(n)=='ConditionalOp' and len(n.conditions)==1:
            c=value(n.conditions[0].expr)
            if c is not None:return value(n.left if c else n.right)
        return None
    if s in f.portexpr:return value(f.portexpr[s])
    if f.outports.get(s):
        vv=[signal_constant(f,v,seen) for v in f.outports[s]]
        return vv[0] if all(v==vv[0] for v in vv) else None
    aa=assignments(f,s)
    if not aa or any(r['sequential'] for n,r in aa):return None
    vv=[value(n.right) for n,r in aa]
    return vv[0] if all(v==vv[0] for v in vv) else None

def branch_details(f,cause,typed):
    # Find a multi-source OR equation nearest to the exception source. This
    # separates input, protection and mode branches before any attribution.
    for row in sorted(cause['evidence'],key=lambda r:r['depth']):
        for node,rec in assignments(f,row['signal']):
            def flatten(n):
                n=strip(n)
                if kind(n)=='BinaryOp' and str(n.op).split('.')[-1] in ('BinaryOr','LogicalOr'):
                    return flatten(n.left)+flatten(n.right)
                return [n]
            terms=flatten(node.right)
            if len(terms)<3:continue
            branches=[]
            for term in terms:
                ss=refs(term)
                if len(ss)!=1:continue
                sig=next(iter(ss));seen,terminal,evidence=cone(f,[sig],typed)
                b4=sorted(v for v in terminal if 'B4' in typed.get(norm(v),{}).get('types',[]))
                equations=[e for e in evidence if e['depth']<=2 or 'access_fault_check' in e['text'] or 'region_basic_perm_check' in e['text'] or 'region_match_all' in e['text']]
                unique={e['source']:e for e in equations}
                branches.append(dict(signal=sig,b4_registers=b4,driver_equations=list(unique.values()),required_relation=sig+' = 0'))
            return branches
    return []

def attach_causes(f,cards,registers):
    typed={r['reg']:r for r in registers}
    for card in cards.values():
        if not any(v.get('operation_class')=='exception' for v in card['contract']['forbid']):continue
        causes=derive_causes(f,card,registers);card['clear_causes']=causes
        permission=[]
        # Identify privilege checks structurally: a selected configuration
        # address compared with the checkpoint's current mode register.
        for n,row in f.assignments:
            rhs=strip(n.right)
            if kind(rhs)=='BinaryOp' and str(rhs.op).split('.')[-1]=='GreaterThan' and kind(strip(rhs.left))=='RangeSelect' and any(norm(v)==norm(card['registers'][0]) for v in refs(rhs.right)):
                permission.append(dict(source=row['file']+':'+str(row['line']),text=' '.join(row['text'].split())))
        for cause in causes.values():
            cause['branches']=branch_details(f,cause,typed)
            cause['permission_checks']=permission
            for branch in cause['branches']:
                cause['probe_signals'].append(branch['signal'])
                branch['constant']=signal_constant(f,branch['signal'])
                branch['requires_before_formation']=bool(permission and branch['b4_registers'] and branch['constant'] is None and not any(r['sequential'] for n,r in assignments(f,branch['signal'])))
                if not branch['requires_before_formation']:continue
                grouped=sorted({re.sub(r'\[\d+\]','[*]',v.rsplit('.',2)[-2]+'.'+v.rsplit('.',1)[-1]) for v in branch['b4_registers']})
                eq=branch['driver_equations'];relations='; '.join(e['text']+' ['+e['source']+']' for e in eq if 'access_fault_check' in e['text'] or 'region_basic_perm_check' in e['text'] or 'region_perm_check' in e['text'])
                text='B4 configuration before formation: '+', '.join(grouped)+', requires '+branch['signal'].rsplit('.',1)[-1]+'=0'
                if relations:text+='; '+relations
                if permission:text+='; write permission: '+permission[0]['text']+' ['+permission[0]['source']+']'
                item=dict(cause=cause['cause'],category=cause['category'],registers=branch['b4_registers'],source=cause['source'],required_relation=branch['required_relation'],requires_before_formation=branch['requires_before_formation'],text=text)
                card['contract']['prerequisites'].append(item)
                card['contract']['forbid'].append(dict(cause=cause['cause'],category=cause['category'],source=cause['source'],text='Cause '+cause['category']+': forbid '+branch['signal'].rsplit('.',1)[-1]+'=1'))
