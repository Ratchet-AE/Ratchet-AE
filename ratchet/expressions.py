"""Typed, JSON-safe predicates shared by synthesis, monitors and diagnosis."""
import operator
OPS={'==':operator.eq,'!=':operator.ne,'>':operator.gt,'>=':operator.ge,'<':operator.lt,'<=':operator.le,'&':operator.and_,'|':operator.or_,'^':operator.xor,'+':operator.add,'-':operator.sub,'*':operator.mul,'<<':operator.lshift,'>>':operator.rshift}
def read(state,key):
    if key in state:return state[key]
    # Fixed packed selectors retain their bit/part identity.
    if key.endswith(']') and '[' in key:
        base,selector=key.rsplit('[',1);selector=selector[:-1]
        value=read(state,base)
        if value is None:return None
        if ':' in selector:
            hi,lo=map(int,selector.split(':'));return (int(value)>>min(hi,lo))&((1<<(abs(hi-lo)+1))-1)
        return (int(value)>>int(selector))&1
    return None

def evaluate(expr,state):
    kind=expr['kind']
    if kind=='const':return expr['value']
    if kind=='ref':return read(state,expr['path'])
    if kind=='all':
        values=[evaluate(x,state) for x in expr['args']]
        return False if False in values else None if None in values else all(values)
    if kind=='any':
        values=[evaluate(x,state) for x in expr['args']]
        return True if True in values else None if None in values else any(values)
    if kind=='not':
        value=evaluate(expr['arg'],state);return None if value is None else not bool(value)
    if kind=='cast':
        value=evaluate(expr['arg'],state)
        if value is None:return None
        value=int(value)&((1<<expr['width'])-1)
        return value-(1<<expr['width']) if expr.get('signed') and value&(1<<(expr['width']-1)) else value
    if kind=='select':
        v=evaluate(expr['arg'],state);i=evaluate(expr['index'],state)
        return None if v is None or i is None else (v>>i)&((1<<expr.get('width',1))-1)
    if kind=='concat':
        value=0
        for part in expr['parts']:
            p=evaluate(part['expr'],state)
            if p is None:return None
            value=(value<<part['width'])|(int(p)&((1<<part['width'])-1))
        return value
    if kind=='ternary':
        c=evaluate(expr['condition'],state)
        return None if c is None else evaluate(expr['yes'] if c else expr['no'],state)
    if kind=='reduce':
        value=evaluate(expr['arg'],state)
        if value is None:return None
        return bool(value) if expr['op']=='|' else value==((1<<expr['width'])-1)
    if kind=='compare':
        left=evaluate(expr['left'],state)
        if left is None:return None
        op=expr['op']
        if op in ('in','not_in'):
            answer=left in expr['values'];return answer if op=='in' else not answer
        right=evaluate(expr['right'],state)
        if right is None:return None
        return OPS[op](left,right)
    raise ValueError('unknown expression '+kind)

def signals(expr):
    out=set()
    def visit(x):
        if isinstance(x,dict):
            if x.get('kind')=='ref':out.add(x['path'])
            for v in x.values():visit(v)
        elif isinstance(x,list):
            for v in x:visit(v)
    visit(expr);return out

def sv(expr):
    k=expr['kind']
    if k=='const':return str(expr['value'])
    if k=='ref':return '$root.'+expr['path']
    if k in ('all','any'):return '('+(' && ' if k=='all' else ' || ').join(sv(v) for v in expr['args'])+')' if expr['args'] else ("1'b1" if k=='all' else "1'b0")
    if k=='not':return '(!'+sv(expr['arg'])+')'
    if k=='cast':return ("$signed(" if expr.get('signed') else "$unsigned(")+str(expr['width'])+"'("+sv(expr['arg'])+'))'
    if k=='select':return '('+sv(expr['arg'])+' >> '+sv(expr['index'])+') & '+str((1<<expr.get('width',1))-1)
    if k=='concat':return '{'+','.join(sv(p['expr']) for p in expr['parts'])+'}'
    if k=='ternary':return '('+sv(expr['condition'])+' ? '+sv(expr['yes'])+' : '+sv(expr['no'])+')'
    if k=='reduce':return '('+expr['op']+sv(expr['arg'])+')'
    if k=='compare':
        left=sv(expr['left'])
        if expr['op'] in ('in','not_in'):
            values=expr['values'];body='('+ ' || '.join(left+' == '+str(v) for v in values)+')' if values else "1'b0"
            return '(!'+body+')' if expr['op']=='not_in' else body
        return '('+left+' '+expr['op']+' '+sv(expr['right'])+')'
    raise ValueError(k)

def condition_expr(c):
    if 'expr' in c:return c['expr']
    left=dict(kind='ref',path=c['signal']);op=c['op'];values=c['values']
    if op in ('in','not_in'):return dict(kind='compare',left=left,op=op,values=values)
    if op=='==' and len(values)>1:return dict(kind='compare',left=left,op='in',values=values)
    if len(values)!=1:raise ValueError('non-scalar comparison')
    return dict(kind='compare',left=left,op=op,right=dict(kind='const',value=values[0]))
