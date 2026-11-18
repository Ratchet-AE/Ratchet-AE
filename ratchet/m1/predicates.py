"""Translate elaborated AST guards; unsupported structures remain explicit."""
from .front import kind,strip,const,refname
BINARY={'Equality':'==','CaseEquality':'==','Inequality':'!=','CaseInequality':'!=','LessThan':'<','LessThanEqual':'<=','GreaterThan':'>','GreaterThanEqual':'>=','BinaryAnd':'&','BinaryOr':'|','BinaryXor':'^','Add':'+','Subtract':'-','Multiply':'*','LogicalShiftLeft':'<<','LogicalShiftRight':'>>'}
def ast_expr(n):
    v=const(n)
    if v is not None:return dict(kind='const',value=v)
    k=kind(n)
    if k=='Conversion':return dict(kind='cast',width=n.type.bitWidth,signed=n.type.isSigned,arg=ast_expr(n.operand))
    if k in ('NamedValue','HierarchicalValue','MemberAccess'):
        s=refname(n)
        if not s:raise ValueError('unbound AST reference')
        return dict(kind='ref',path=s)
    if k=='ElementSelect':return dict(kind='select',arg=ast_expr(n.value),index=ast_expr(n.selector))
    if k=='RangeSelect':
        left=const(n.left);right=const(n.right)
        if left is None or right is None:raise ValueError('dynamic part selection')
        return dict(kind='select',arg=ast_expr(n.value),index=dict(kind='const',value=min(left,right)),width=abs(left-right)+1)
    if k=='UnaryOp':
        op=str(n.op).split('.')[-1]
        if op=='LogicalNot':return dict(kind='not',arg=ast_expr(n.operand))
        if op in ('BitwiseOr','BitwiseAnd'):return dict(kind='reduce',op='|' if op=='BitwiseOr' else '&',width=n.operand.type.bitWidth,arg=ast_expr(n.operand))
        if op=='BitwiseNot':return dict(kind='compare',left=ast_expr(n.operand),op='^',right=dict(kind='const',value=(1<<n.type.bitWidth)-1))
    if k=='BinaryOp':
        op=str(n.op).split('.')[-1]
        if op in ('LogicalAnd','LogicalOr'):return dict(kind='all' if op=='LogicalAnd' else 'any',args=[ast_expr(n.left),ast_expr(n.right)])
        if op in BINARY:return dict(kind='compare',left=ast_expr(n.left),op=BINARY[op],right=ast_expr(n.right))
    if k=='Concatenation':return dict(kind='concat',parts=[dict(width=v.type.bitWidth,expr=ast_expr(v)) for v in n.operands])
    if k=='ConditionalOp' and len(n.conditions)==1:return dict(kind='ternary',condition=ast_expr(n.conditions[0].expr),yes=ast_expr(n.left),no=ast_expr(n.right))
    if k=='Inside':
        values=[const(v) for v in n.rangeList]
        if None not in values:return dict(kind='compare',left=ast_expr(n.left),op='in',values=values)
    raise ValueError('unsupported guard AST '+k)

def writer_guards(f,node):
    from .front import contains,span
    guards=[];gaps=[]
    for cs,cc,neg in f.conds_by_buffer[span(node)[0]]:
        if contains(cs,span(node)) and f.guard_applies(node,cc):
            try:
                e=dict(kind='all',args=[ast_expr(c) for c in cc]);guards.append(dict(kind='not',arg=e) if neg else e)
            except ValueError as ex:gaps.append(str(ex))
    for cs,sel,vals in f.cases_by_buffer[span(node)[0]]:
        if contains(cs,span(node)) and vals and f.guard_applies(node,[sel,*vals]):
            try:guards.append(dict(kind='any',args=[dict(kind='compare',op='==',left=ast_expr(sel),right=ast_expr(v)) for v in vals]))
            except ValueError as ex:gaps.append(str(ex))
    return dict(kind='all',args=guards),gaps
