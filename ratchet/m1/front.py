"""Elaborated AST front end. No regex RTL classification and no trace IO."""
from pathlib import Path
from collections import defaultdict,deque
import json,hashlib
import pyslang as sl
from ..lib.static_engine import Engine,kind,refs,lhsrefs,refname,span

def strip(n):
    while n is not None and kind(n)=='Conversion':n=n.operand
    return n

EVAL_CONTEXT=None
def const(n):
    try:
        v=n.constant
        if v is None and EVAL_CONTEXT is not None:v=n.eval(EVAL_CONTEXT)
        return int(v.value)
    except (AttributeError,ValueError,TypeError,RuntimeError):return None

def reset_branch(c,neg):
    cc=strip(c);names=refs(cc)
    if len(names)!=1:return False
    leaf=next(iter(names)).rsplit('.',1)[-1].lower()
    if not leaf.startswith(('rst','reset')):return False
    inverted=kind(cc)=='UnaryOp' and str(cc.op).split('.')[-1]=='LogicalNot'
    active_low=leaf.endswith(('_ni','_n','rstn','resetn'))
    return (inverted != neg) if active_low else (inverted == neg)

def norm(s):
    parts=s.split('.')
    if parts[-1].endswith(('_q','_d','_cs','_ns')):parts[-1]=parts[-1].rsplit('_',1)[0]
    return '.'.join(parts)

def control_reads(node):
    """Direct value-compressing/control reads; never infer purity from writers.

    Run on the elaborated AST, including LHS indices and conditions that also
    appear in RHS data. Dependency closure below crosses assignments/ports and
    projects aggregate members through the existing instance-aware graph.
    """
    k=kind(node);out=set()
    if k in ('Conditional','ConditionalOp'):
        for condition in node.conditions:out.update(refs(condition.expr))
    elif k in ('Case','PatternCase'):
        out.update(refs(node.expr))
        for item in node.items:
            for expression in getattr(item,'expressions',()):out.update(refs(expression))
    elif k=='BinaryOp' and str(node.op).split('.')[-1] in (
        'Equality','CaseEquality','WildcardEquality','Inequality',
        'CaseInequality','WildcardInequality','GreaterThan','GreaterThanEqual',
        'LessThan','LessThanEqual','LogicalAnd','LogicalOr','LogicalImplication',
        'LogicalEquivalence'):
        out.update(refs(node))
    elif k=='UnaryOp' and str(node.op).split('.')[-1] in (
        'BitwiseAnd','BitwiseOr','BitwiseXor','BitwiseNand','BitwiseNor','BitwiseXnor','LogicalNot'):
        out.update(refs(node.operand))
    elif k=='Call' and str(getattr(node.subroutine,'subroutine','')) in (
        '$countbits','$countones','$onehot','$onehot0','$isunknown'):
        for argument in node.arguments:out.update(refs(argument))
    elif k=='Inside':out.update(refs(node))
    elif k=='ElementSelect':out.update(refs(node.selector))
    elif k=='RangeSelect':
        out.update(refs(node.left));out.update(refs(node.right))
    elif k in ('ForLoop','WhileLoop','DoWhileLoop','RepeatLoop'):
        for name in ('stopExpr','cond','count'):
            expression=getattr(node,name,None)
            if expression is not None:out.update(refs(expression))
    return out

class Front(Engine):
    def __init__(self,cfg):
        self.assignments=[]
        super().__init__(cfg)
        if self.diagnostics:raise RuntimeError('Elaboration errors: '+json.dumps(self.diagnostics[:8]))
        global EVAL_CONTEXT
        self.ctx=sl.ast.EvalContext(self.top.body);EVAL_CONTEXT=self.ctx;self.conds=[];self.cases=[];self.controls=[];self.ass=defaultdict(list);self.portexpr={};self.outports=defaultdict(list);self.reset={};self.fwd=defaultdict(set);self.control_seeds=set()
        for n,rec in self.assignments:
            for sig in rec['lhs']:self.ass[sig].append((n,rec))
        def visit(n):
            k=kind(n)
            if k=='GenerateBlock' and n.isUninstantiated:return sl.ast.VisitAction.Skip
            if k in ('ClassType','Covergroup'):return sl.ast.VisitAction.Skip
            self.control_seeds.update(control_reads(n))
            if k=='Call' and hasattr(n.subroutine,'arguments'):
                # A parameter read inside a pure function must reach its actual
                # arguments even when the control only selects a return value.
                for parameter,actual in zip(n.subroutine.arguments,n.arguments):
                    self.reverse[parameter.hierarchicalPath].update(refs(actual))
            if k=='Conditional':
                self.controls.append(dict(file=str(self.sm.getFileName(n.sourceRange.start)),line=self.sm.getLineNumber(n.sourceRange.start),kind='if'))
                for b,neg in ((n.ifTrue,False),(n.ifFalse,True)):
                    if b is not None:self.conds.append((span(b),[c.expr for c in n.conditions],neg))
            if k=='Case':
                self.controls.append(dict(file=str(self.sm.getFileName(n.sourceRange.start)),line=self.sm.getLineNumber(n.sourceRange.start),kind='case'))
                for item in n.items:self.cases.append((span(item.stmt),n.expr,list(item.expressions)))
            if k=='Instance':
                for pc in n.portConnections:
                    inside=refs(pc.port.internalExpr) if pc.port.internalExpr is not None else {pc.port.internalSymbol.hierarchicalPath} if pc.port.internalSymbol else set()
                    direction=str(pc.port.direction).split('.')[-1]
                    if direction=='In' and pc.expression is not None:
                        for s in inside:self.portexpr[s]=pc.expression
                    if direction=='Out' and pc.expression is not None and len(inside)==1:
                        expr=pc.expression.left if kind(pc.expression)=='Assignment' else pc.expression
                        out=refname(expr)
                        if out:self.outports[out].append(next(iter(inside)))
        self.top.visit(visit)
        for target,ss in self.reverse.items():
            for s in ss:self.fwd[s].add(target)
        self.writers={}
        self.norm_regs={norm(s) for s in self.regs}
        self.conds_by_buffer=defaultdict(list);self.cases_by_buffer=defaultdict(list)
        for row in self.conds:self.conds_by_buffer[row[0][0]].append(row)
        for row in self.cases:self.cases_by_buffer[row[0][0]].append(row)
        for n,r in self.assignments:
            if r['sequential'] and const(n.right) is not None:
                for s in r['lhs']:
                    for cs,conds,neg in self.conds_by_buffer[span(n)[0]]:
                        if contains(cs,span(n)) and any(reset_branch(c,neg) for c in conds):self.reset[norm(s)]=const(n.right)
        self.relevant=set(self.control_seeds)
        q=deque(self.relevant)
        while q:
            s=q.popleft()
            dependencies,_=self.predecessors(s)
            for dependency in dependencies:
                if dependency not in self.relevant:
                    self.relevant.add(dependency);q.append(dependency)
        self.sample_observers=[p for p,m in self.instances.items() if m=='xb_ibex_sample_if' and p.startswith(self.c['seed_base']+'.')]
        self.relevant_parents=set(self.relevant)
        for s in self.relevant:
            parts=s.split('.')
            for i in range(1,len(parts)):self.relevant_parents.add('.'.join(parts[:i]))
    def _assignment(self,a,control,seq,path):
        super()._assignment(a,control,seq,path)
        self.assignments.append((a,self.statements[-1]))
    def external(self,signals,max_depth=8):
        q=deque((s,0) for s in signals);seen=set()
        while q:
            s,d=q.popleft()
            if s in seen:continue
            seen.add(s)
            if self.isboundary(s):return s
            if d>=max_depth:continue
            ps,_=self.predecessors(s)
            q.extend((p,d+1) for p in sorted(ps))
        return None
    def is_control_relevant(self,signal):
        if signal in self.relevant_parents:return True
        # Reading a whole aggregate also reads assignments to its fields.
        parts=signal.split('.')
        return any('.'.join(parts[:i]) in self.relevant for i in range(1,len(parts)))
    def classify(self,observed):
        result=[]
        for a,r in self.assignments:
            ls=set(r['lhs']);rs=refs(a.right);v=const(a.right);seq=r['sequential'] or any(norm(x) in self.norm_regs for x in ls)
            types=set();proof={};selects=[];ops=[]
            def select(n):
                if kind(n)=='ElementSelect' and const(n.selector) is None:selects.append((str(n.selector.syntax).strip(),refs(n.selector),self.external(refs(n.selector))))
            a.left.visit(select)
            def operation(n):
                if kind(n)=='BinaryOp':ops.append((str(n.op).split('.')[-1],refs(n),n))
            a.right.visit(operation)
            if any(s in observed for s in ls):types.add('V');proof['V']='raw sample signal or lossless scalar alias'
            control=any(self.is_control_relevant(s) for s in ls)
            if not control and not any(s in observed for s in ls):types.add('D');proof['D']='no static dataflow to branch/comparison or raw sample'
            if seq:
                if v is not None and any(v==0 or self.reset.get(norm(s))==v for s in ls):types.add('B2');proof['B2']='zero or AST reset value assignment'
                for op,sigs,node in ops:
                    self_update=any(norm(s)==norm(t) for s in ls for t in sigs)
                    if op in ('Add','Subtract','BinaryOr') and self_update:types.add('B1');proof['B1']='self arithmetic/set-mask accumulation'
                    if op=='BinaryAnd' and self_update:
                        complements=[]
                        node.visit(lambda n: complements.append(True) if kind(n)=='UnaryOp' and str(n.op).split('.')[-1]=='BitwiseNot' else None)
                        if complements:types.add('B2');proof['B2']='self AND complemented mask'
                if a.isCompound and str(a.op).split('.')[-1] in ('Add','Subtract','BinaryOr'):types.add('B1');proof['B1']='compound accumulation'
                if any(ext for _,_,ext in selects):types.add('B3');proof['B3']='dynamic LHS index reaches input in <=8 dataflow steps'
                elif selects and v is not None and v>0:types.add('B1');proof['B1']='set internally allocated indexed entry'
                # Mode/configuration roles are taken from explicit configuration
                # direct_patterns and declared privilege/mubi enum types.
                for s in ls:
                    sym=self.symbols.get(s)
                    typename=str(sym.type) if sym is not None else ''
                    path=s.split('.')
                    role=any(p in ('cs_registers_i','u_reg','u_reg_top') for p in path) or any(t in typename for t in ('priv_lvl_e','privilege_level_t','mubi4_t'))
                    if role and control and 'B1' not in types:types.add('B4');proof['B4']='elaborated CSR/configuration instance or declared privilege/mubi mode type'
            if not types:
                # Unrecognized control state is never evidence of pure data.
                types.add('V' if control or not seq else 'D')
                proof['fallback']='control-relevant selection/value routing' if control else 'unclassified state with no control readers'
            # A V line stays visible, but aggregate all B2 writes for loss_hidden.
            primary='V' if 'V' in types else next((t for t in ('B2','B4','B3','B1') if t in types),'D')
            reset_only=any(contains(cs,span(a)) and any(reset_branch(c,neg) for c in cc) for cs,cc,neg in self.conds_by_buffer[span(a)[0]])
            record=dict(r,end=self.sm.getLineNumber(a.sourceRange.end),reset_only=reset_only,types=sorted(types),primary=primary,proof=proof,rhs_const=v,index_sources=[dict(expr=s,signals=sorted(q),source='input' if ext else 'internal',witness=ext) for s,q,ext in selects],seq=seq,observed=bool(ls&observed),guards=self.guards(a))
            result.append(record)
        return result
    def guard_applies(self,node,expressions):
        instance=self._instance(refname(node.left) or '')
        owners={self._instance(s) for e in expressions for s in refs(e)}-{''}
        return not owners or instance in owners
    def guards(self,a):
        out=[]
        for cs,cc,neg in self.conds_by_buffer[span(a)[0]]:
            if contains(cs,span(a)) and self.guard_applies(a,cc):out.extend(dict(expr=str(c.syntax).strip(),negated=neg,signals=sorted(refs(c))) for c in cc)
        for cs,sel,vals in self.cases_by_buffer[span(a)[0]]:
            if contains(cs,span(a)) and self.guard_applies(a,[sel,*vals]):out.append(dict(expr=str(sel.syntax).strip(),case_values=[const(v) for v in vals],signals=sorted(refs(sel))))
        return out

def contains(a,b):return a[0]==b[0] and a[1]<=b[1] and b[2]<=a[2]

def syntax_expression(expr):
    tree=sl.syntax.SyntaxTree.fromText('module __sample; initial if ('+expr+') ; endmodule');found=[]
    tree.root.visit(lambda n:found.append(n.predicate.conditions[0]) if str(getattr(n,'kind',''))=='SyntaxKind.ConditionalStatement' else None)
    # The condition is an expression or an expression-or-pattern wrapper.
    node=found[0]
    if hasattr(node,'expr'):node=node.expr
    return tree,node

def syntax_signals(expr,base,all_nodes):
    tree,n=syntax_expression(expr);found=set()
    def visit(v):
        k=str(getattr(v,'kind','')).split('.')[-1]
        if k in ('ScopedName','IdentifierName') and str(getattr(getattr(v,'parent',None),'kind','')).split('.')[-1]!='ScopedName':
            name=str(v).strip();candidate=base+'.'+name
            if candidate in all_nodes:found.add(candidate);return sl.syntax.VisitAction.Skip if hasattr(sl.syntax,'VisitAction') else None
    n.visit(visit)
    return found
