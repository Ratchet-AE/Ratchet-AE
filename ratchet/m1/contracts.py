"""Writer/guard-derived formation paths and clearing contracts, not bin templates."""
from .front import norm,kind,refname,strip,const,contains,span
from .predicates import ast_expr,writer_guards
from ..expressions import signals
from ..m2.render import expression

def canonical(path):return '.'.join(p[:-2] if p.endswith(('_q','_d')) else p for p in path.split('.'))

def field_value(node,lhs,path):
    for target in lhs:
        if canonical(target)==canonical(path):return node.right
        if canonical(path).startswith(canonical(target)+'.') and kind(strip(node.right))=='StructuredAssignmentPattern':
            name=canonical(path)[len(canonical(target))+1:];pattern=strip(node.right)
            members=[m for m in pattern.type.canonicalType if hasattr(m,'type')]
            for m,e in zip(members,pattern.elements):
                if m.name==name:return e
    return None

def enriched_guard(f,node):
    guard,gaps=writer_guards(f,node)
    # A case's earlier matching arm has priority. Add it for contract operations
    # only; the previously frozen Cost/p_clr calculation is left unchanged.
    extra=[]
    def visit(n):
        if kind(n)!='Case' or not contains(span(n),span(node)):return
        if not f.guard_applies(node,[n.expr,*[v for item in n.items for v in item.expressions]]):return
        before=[]
        for item in n.items:
            if contains(span(item.stmt),span(node)):
                for v in before:
                    try:extra.append(dict(kind='not',arg=dict(kind='compare',op='==',left=ast_expr(n.expr),right=ast_expr(v))))
                    except ValueError:pass
                break
            before.extend(item.expressions)
    f.top.visit(visit)
    return dict(kind='all',args=[guard,*extra]),gaps

def describe_source(f,source,value):
    """Find field writers through q/d storage and structured assignment patterns."""
    result=[]
    for node,row in f.assignments:
        rhs=field_value(node,row['lhs'],source)
        if rhs is None or const(rhs) is not None:continue
        if refname(strip(rhs))==source:continue
        guard,gaps=writer_guards(f,node)
        if gaps:continue
        ss=signals(guard)
        # A CSR write is identified by its elaborated CSR address guard, not a bin.
        if not any(s.rsplit('.',1)[-1].startswith('csr_addr') for s in ss):continue
        try:expr=ast_expr(rhs)
        except ValueError:continue
        result.append(dict(source=row['file']+':'+str(row['line']),guard=guard,value_expression=expr,required_value=value,text='Configure '+source.rsplit('.',2)[-2]+'.'+source.rsplit('.',1)[-1]+' = '+str(value)+': write '+expression(expr)+' = '+str(value)+'; guard '+expression(guard)))
    return result

def generate_contract(f,condition,reg,clear,register_sources):
    wanted=condition['values'][0] if condition['op']=='==' and len(condition['values'])==1 else None
    form=[];paths=[]
    if 'B4' in reg['types'] and wanted is not None:
        for node,row in register_sources[reg['reg']]:
            if row['file']+':'+str(row['line']) in reg['reset_writers']:continue
            rhs=strip(node.right);source=refname(rhs)
            if source and norm(source)==reg['reg']:continue  # hold / q<-d latch
            value=const(rhs)
            if value is not None and value!=wanted:continue
            guard,gaps=enriched_guard(f,node)
            if gaps:continue
            try:rhs_expr=ast_expr(rhs)
            except ValueError:continue
            guard_names=signals(guard);restore=next((s.rsplit('.',1)[-1] for s in guard_names if s.rsplit('.',1)[-1].startswith('csr_restore_')),None)
            instruction=restore.removeprefix('csr_restore_').removesuffix('_i').upper() if restore else None
            prerequisites=describe_source(f,source,wanted) if source else []
            if instruction:
                for step in prerequisites:form.append(step)
                form.append(dict(source=row['file']+':'+str(row['line']),guard=guard,requires=dict(expression=rhs_expr,value=wanted),operation=instruction,text='Execute '+instruction+'; requires '+expression(rhs_expr)+' = '+str(wanted)+'; guard '+expression(guard)))
                paths.append(dict(operation=instruction,requires=source or value,steps=prerequisites))
    if not form:form=[dict(predicate=condition['expr'],writer_lines=reg['writer_lines'],text='Form '+expression(condition['expr'])+'; satisfy the advance guard using the listed RTL assignments')]
    # Normal instruction-return paths before debug-return alternatives.
    form.sort(key=lambda x:('DRET' in x.get('text',''),x.get('source','')))
    forbid=[]
    for v in clear:
        forbid.append(dict(guard=v['expr'],source=v['source'],operation_class=v['evidence'].get('operation_type','unknown'),text='Forbidden within window '+expression(v['expr'])+'; this clearing assignment writes the state to '+str(v['value'])+(' (trap/exception/interrupt save cause; return to M-mode)' if v['evidence'].get('operation_type')=='exception' else '')))
    return dict(form=form,forbid=forbid,prerequisites=[],formation_paths=paths,derivation='elaborated writer RHS, field writers, CSR guards and case-arm priorities')
