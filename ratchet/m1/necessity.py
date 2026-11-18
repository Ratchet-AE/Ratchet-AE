"""Structural necessary conditions and bounded same-cycle DNF."""
from collections import deque
from .front import kind,refs,refname,strip,const,span,contains,syntax_expression
from .alternatives import DNF
import json

def atom(sig,op,values):return (sig,op,tuple(sorted(values)))

def literal(text):
    text=text.strip().replace('_','')
    try:
        if "'" not in text:return int(text,10)
        width,raw=text.split("'",1);raw=raw.lstrip('sS')
        if raw in ('0','1'):return int(raw)
        return int(raw[1:],{'b':2,'o':8,'d':10,'h':16}[raw[0].lower()])
    except (ValueError,KeyError):return None

class Necessity:
    def __init__(self,front):self.f=front;self.events=[];self.or_count=0;self.alternatives=[];self.conditional_conditions=[];self.producer_cache={};self.parameters={};self.call_depth=0
    def unknown(self,why,source,dom=False):
        event=dict(dom_kind='dom_unknown' if dom else 'unresolved_implementation',reason=why,source=source)
        if event not in self.events:self.events.append(event)
        return DNF.unknown()
    def checked(self,d):
        for reason in d.overflow:self.unknown(reason,'bounded DNF',dom=True)
        return d
    def selected(self,n):
        """Fixed selections are monitorable scalar requirements, not base-wide values."""
        n=strip(n);s=refname(n) if kind(n) not in ('ElementSelect','RangeSelect') else None
        if s:
            return self.selected(self.parameters[s]) if s in self.parameters else s
        k=kind(n)
        if k=='ElementSelect':
            base=self.selected(n.value);index=const(n.selector)
            if base is not None and index is not None:return base+'['+str(index)+']'
        if k=='RangeSelect':
            base=self.selected(n.value);left=const(n.left);right=const(n.right)
            if base is not None and left is not None and right is not None:return base+'['+str(left)+':'+str(right)+']'
        return None
    def negated_equality(self,n,value):
        s=self.selected(n)
        if s:return DNF.one(atom(s,'!=',[value]))
        if n.type.bitWidth==1:return self.ast_atoms(n,1-value)
        return self.unknown('unsupported composite negated equality',str(n.syntax))
    def boolean(self,n,want):
        return self.ast_atoms(n,want) if n.type.bitWidth==1 or not want else self.negated_equality(n,0)
    def ast_atoms(self,n,want=1):
        n=strip(n);v=const(n)
        if v is not None:return DNF.truth() if v==want else DNF.false()
        k=kind(n)
        if k in ('NamedValue','HierarchicalValue','MemberAccess','ElementSelect','RangeSelect'):
            s=self.selected(n)
            return DNF.one(atom(s,'==',[want])) if s else self.unknown('dynamic object selection requires index binding',str(n.syntax))
        if k=='UnaryOp':
            op=str(n.op).split('.')[-1]
            if op=='LogicalNot':return self.boolean(n.operand,int(not want))
            if op=='BitwiseNot':return self.ast_atoms(n.operand,(~want)&((1<<n.operand.type.bitWidth)-1))
            if op in ('BitwiseAnd','BitwiseOr'):
                if kind(strip(n.operand))=='Concatenation':
                    # Reduction of a concatenation is a Boolean AND/OR over
                    # per-operand reductions; don't mistake it for a scalar ref.
                    conjunction=(op=='BitwiseAnd')==bool(want)
                    result=DNF.truth() if conjunction else DNF.false()
                    for value in strip(n.operand).operands:
                        bits=(1<<value.type.bitWidth)-1 if op=='BitwiseAnd' else 0
                        equal=bool(want) if op=='BitwiseAnd' else not bool(want)
                        part=self.ast_atoms(value,bits) if equal else self.negated_equality(value,bits)
                        result=(result & part) if conjunction else (result | part)
                    if not conjunction:self.or_count+=1
                    return self.checked(result)
                s=self.selected(n.operand)
                if s:
                    value=(1<<n.operand.type.bitWidth)-1 if op=='BitwiseAnd' else 0
                    equal=bool(want) if op=='BitwiseAnd' else not bool(want)
                    return DNF.one(atom(s,'==' if equal else '!=',[value]))
            return self.unknown('unsupported unary requirement: '+op,str(n.syntax))
        if k=='BinaryOp':
            op=str(n.op).split('.')[-1]
            boolean=n.type.bitWidth==1
            if op in ('LogicalAnd','LogicalOr') or boolean and op in ('BinaryAnd','BinaryOr'):
                a=self.boolean(n.left,want);b=self.boolean(n.right,want)
                conjunction=(op in ('LogicalAnd','BinaryAnd'))==bool(want)
                if not conjunction:self.or_count+=1
                return self.checked((a & b) if conjunction else (a | b))
            comparators={'Equality':'==','CaseEquality':'==','Inequality':'!=','CaseInequality':'!=','GreaterThan':'>','GreaterThanEqual':'>=','LessThan':'<','LessThanEqual':'<='}
            if op in ('BinaryOr','BinaryAnd') and (op=='BinaryOr' and want==0 or op=='BinaryAnd' and want==(1<<n.type.bitWidth)-1):
                return self.checked(self.ast_atoms(n.left,want) & self.ast_atoms(n.right,want))
            if op in comparators:
                s=self.selected(n.left);v=const(n.right);out=comparators[op]
                if s is None or v is None:
                    s=self.selected(n.right);v=const(n.left)
                    out={'==':'==','!=':'!=','>':'<','>=':'<=','<':'>','<=':'>='}[out]
                if s is not None and v is not None:
                    if not want:out={'==':'!=','!=':'==','>':'<=','>=':'<','<':'>=','<=':'>'}[out]
                    return DNF.one(atom(s,out,[v]))
            return self.unknown('unsupported relational/arithmetic operands: '+op,str(n.syntax))
        if k=='ConditionalOp':
            if len(n.conditions)!=1:return self.unknown('conditional pattern matching unsupported',str(n.syntax))
            condition=n.conditions[0].expr
            self.or_count+=1
            return self.checked((self.boolean(condition,1)&self.ast_atoms(n.left,want))|(self.boolean(condition,0)&self.ast_atoms(n.right,want)))
        if k=='Concatenation':
            result=DNF.truth();offset=0
            for operand in reversed(list(n.operands)):
                width=operand.type.bitWidth;mask=(1<<width)-1
                result=result & self.ast_atoms(operand,(want>>offset)&mask);offset+=width
            return self.checked(result)
        if k=='Inside':
            s=self.selected(n.left)
            if s:
                values=[]
                for item in n.rangeList:
                    value=const(item)
                    if value is None:return self.unknown('inside nonconstant/range element',str(n.syntax))
                    values.append(value)
                # Membership is one exact scalar condition, not an expanded OR
                # of already-enumerated scalar values.
                return DNF.one(atom(s,'in' if want else 'not_in',values))
        if k=='Call':
            if not n.isSystemCall and kind(n.subroutine.body)=='Case' and self.call_depth<8:
                body=n.subroutine.body;previous=self.parameters.copy();self.call_depth+=1
                try:
                    self.parameters.update({a.hierarchicalPath:b for a,b in zip(n.subroutine.arguments,n.arguments)})
                    key=self.selected(body.expr);known=[];accepted=[]
                    if key and all(kind(item.stmt)=='Return' and const(item.stmt.expr) is not None for item in body.items):
                        for item in body.items:
                            values=[const(v) for v in item.expressions]
                            if None in values:break
                            known.extend(values)
                            if const(item.stmt.expr)==want:accepted.extend(values)
                        else:
                            default=body.defaultCase
                            if default is not None and kind(default)=='Return' and const(default.expr) is not None:
                                if const(default.expr)==want:
                                    rejected=sorted(set(known)-set(accepted))
                                    return DNF.one(atom(key,'not_in',rejected))
                                return DNF.one(atom(key,'in',accepted)) if accepted else DNF.false()
                finally:self.parameters=previous;self.call_depth-=1
            if not n.isSystemCall and kind(n.subroutine.body)=='Return' and self.call_depth<8:
                previous=self.parameters.copy();self.call_depth+=1
                try:
                    self.parameters.update({a.hierarchicalPath:b for a,b in zip(n.subroutine.arguments,n.arguments)})
                    return self.ast_atoms(n.subroutine.body.expr,want)
                finally:self.parameters=previous;self.call_depth-=1
            name=str(n.subroutineName)
            if n.arguments and ('mubi4_test_true_strict' in name or 'mubi4_test_false_strict' in name):
                s=self.selected(n.arguments[0]);return DNF.one(atom(s,'==' if want else '!=',[6 if 'true' in name else 9])) if s else self.unknown('MuBi argument binding',str(n.syntax))
        return self.unknown('unsupported expression kind '+k,str(getattr(n,'syntax','')))
    def syntax_atoms(self,expr,want=1):
        tree,n=syntax_expression(expr);base=self.f.c['seed_base']
        def recurse(v,expected):
            k=str(v.kind).split('.')[-1]
            if k in ('IdentifierName','ScopedName'):
                s=base+'.'+str(v).strip()
                if s not in self.f.all_nodes:
                    choices=[p+'.'+str(v).strip() for p in self.f.sample_observers if p+'.'+str(v).strip() in self.f.all_nodes]
                    if len(choices)==1:s=choices[0]
                    else:return self.unknown('sample expression outside elaborated DUT: '+s,expr)
                return DNF.one(atom(s,'==',[expected]))
            if k=='ParenthesizedExpression':return recurse(v.expression,expected)
            if k=='UnaryLogicalNotExpression':return recurse(v.operand,int(not expected))
            if k in ('LogicalAndExpression','BinaryAndExpression','LogicalOrExpression','BinaryOrExpression'):
                conjunction=(k in ('LogicalAndExpression','BinaryAndExpression'))==bool(expected)
                a=recurse(v.left,expected);b=recurse(v.right,expected)
                if not conjunction:self.or_count+=1
                return self.checked((a & b) if conjunction else (a | b))
            return self.unknown('sample expression not projected: '+k,expr)
        return recurse(n,want)
    def producer(self,s,want):
        cache_key=(s,want)
        if cache_key in self.producer_cache:return self.producer_cache[cache_key]
        result=self._producer(s,want);self.producer_cache[cache_key]=result
        return result
    def _producer(self,s,want):
        f=self.f
        if s in f.portexpr:return self.ast_atoms(f.portexpr[s],want)
        if len(f.outports.get(s,[]))==1:return DNF.one(atom(f.outports[s][0],'==',[want]))
        aa=f.ass.get(s,[])
        if not aa:return None  # A dependency edge alone does not prove a value-preserving alias.
        alternatives=[]
        for n,r in aa:
            value=const(n.right)
            if value is not None and value!=want:continue
            if refname(strip(n.right))==s:continue
            zz=self.ast_atoms(n.right,want)
            for cs,conds,neg in f.conds_by_buffer[span(n)[0]]:
                if contains(cs,span(n)) and f.guard_applies(n,conds):
                    # A negated multi-condition if is OR, not AND.
                    guard=DNF.false() if neg else DNF.truth()
                    for c in conds:guard=(guard|self.boolean(c,0)) if neg else (guard&self.boolean(c,1))
                    zz=zz & guard
            for cs,selector,vals in f.cases_by_buffer[span(n)[0]]:
                if contains(cs,span(n)) and f.guard_applies(n,[selector,*vals]):
                    key=self.selected(selector);vv=[const(v) for v in vals];sv=const(selector)
                    if key and vv and None not in vv:zz=zz & DNF.one(atom(key,'in',vv))
                    elif sv is not None and vals:
                        case_guard=DNF.false()
                        for value in vals:case_guard=case_guard | self.ast_atoms(value,sv)
                        zz=zz & case_guard
                    elif vals:zz=zz & self.unknown('nonconstant case label relation',str(selector.syntax))
            if zz.complete and not zz.branches:continue
            alternatives.append(self.checked(zz))
        if not alternatives:return None
        if len(alternatives)>1:
            self.unknown('multiple writer paths: keep only exact common requirements',s,dom=True)
            common=set.intersection(*(v.common() for v in alternatives))
            result=DNF.truth()
            for a in sorted(common):result=result & DNF.one(a)
            return result
        return alternatives[0]
    def same_cycle(self,initial):
        def expand(a,path):
            s,op,vals=a
            if a in path or len(path)>=60:
                self.unknown('same-cycle dependency cycle or depth cap',s,dom=True);return DNF.one(a)&DNF.unknown()
            if op!='==' or len(vals)!=1 or self.f.regkeys(s):return DNF.one(a)
            derived=self.producer(s,vals[0])
            if derived is None or derived.complete and derived.branches==(frozenset(),):return DNF.one(a)
            result=DNF.false()
            for branch in derived.branches:
                part=DNF.truth()
                for b in branch:part=part & expand(b,path+(a,))
                result=result | part
            if not derived.complete:result=(result if result.branches else DNF.truth()) & DNF.unknown()
            return self.checked(result)
        result=DNF.false()
        for branch in initial.branches:
            part=DNF.truth()
            for a in branch:part=part & expand(a,())
            result=result | part
        if not initial.complete:result=(result if result.branches else DNF.truth()) & DNF.unknown()
        return self.checked(result)
    def propagate(self,initial):
        # All alternatives are same-cycle; sequential predecessor obligations
        # remain separate and are never folded into a same-cycle conjunction.
        simultaneous=self.same_cycle(initial)
        self.alternatives=[dict(id='a'+str(i),conditions=[dict(signal=s,op=op,values=list(v)) for s,op,v in sorted(branch)]) for i,branch in enumerate(simultaneous.branches) if branch]
        self.alternatives_complete=simultaneous.complete
        common=simultaneous.common()
        memberships={}
        for alternative in self.alternatives:
            for c in alternative['conditions']:
                a=atom(c['signal'],c['op'],c['values']);memberships.setdefault(a,[]).append(alternative['id'])
        self.conditional_conditions=[dict(signal=s,op=op,values=list(v),dom_kind='conditional necessity',alternative_ids=ids,is_candidate=False) for (s,op,v),ids in sorted(memberships.items()) if (s,op,v) not in common]
        required=initial.common()|common
        found={a:dict(depth=0,dom_kind='atom_required') for a in required};queue=deque((a,0,0) for a in required);seen=set()
        while queue:
            a,depth,hops=queue.popleft()
            if a in seen or depth>=8 or hops>=60:continue
            seen.add(a);s,op,vals=a
            if op!='==' or len(vals)!=1:continue
            seq=bool(self.f.regkeys(s));derived=self.producer(s,vals[0])
            if derived is None:continue
            for req in derived.common():
                if req not in found:
                    found[req]=dict(depth=depth+int(seq),dom_kind='seq_necessary' if seq else 'atom_required');queue.append((req,depth+int(seq),hops+1))
        return [dict(signal=s,op=op,values=list(vv),**info) for (s,op,vv),info in sorted(found.items())]

    def bin_start(self,dut,target,cov,sampling,maps):
        if dut=='hpdcache':
            t=target['target'];return DNF.one(atom(self.f.c['seed_base']+'.hpdcache_ctrl_i.hpdcache_ctrl_pe_i.'+t['event_signal'],'==',[1])) & DNF.one(atom(self.f.c['seed_base']+'.hpdcache_ctrl_i.hpdcache_ctrl_pe_i.'+t['reason_signal'],'==',[1]))
        gname,point=target['group_id'].split('.',1);group=cov.groups.get(gname)
        if group is None:return self.unknown('group unavailable in frozen coverage model',gname)
        if point in group.points:parts=[(point,target['bin_name'])]
        elif point in group.crosses:parts=list(zip(group.crosses[point],target['bin_name'].strip('<>').split(',')))
        else:return self.unknown('point unavailable in frozen coverage model',point)
        start=DNF.truth()
        for cp_name,bname in parts:
            cp=group.points[cp_name];b=next((b for b in cp.bins if b.name==bname),None)
            if b is None:self.unknown('bin unavailable in frozen coverage model',bname);continue
            if dut=='ibex':
                expr=sampling.get(cp_name)
                if expr is None:self.unknown('sample mapping absent',cp_name);continue
                def sample(v):return self.syntax_atoms(expr,v)
            else:
                ss=maps.get(gname+'.'+cp_name,{}).get('resolved_seeds',[])
                if len(ss)!=1:self.unknown('non-atomic es sample binding: '+str(len(ss)),cp_name);continue
                def sample(v):return DNF.one(atom(ss[0],'==',[v]))
            values=set(b.values)
            if b.ranges:
                if len(b.ranges)==1 and b.ranges[0][0]==b.ranges[0][1]:values.add(b.ranges[0][0])
                else:self.unknown('range-valued sample requires interval projection',cp_name)
            if b.transitions:
                self.unknown('transition history: static predecessor obligation not yet projected',cp_name)
                continue
            if len(values)==1:start=start & sample(next(iter(values)))
            elif len(values)>1:
                choice=DNF.false()
                for value in sorted(values):choice=choice | sample(value)
                start=start & choice
            else:self.unknown('predicate/wildcard sample not projected',cp_name)
            if dut=='ibex' and cp_name in ('cp_dummy_instr','cp_data_ind_timing_instr'):
                signal='dummy_instr_en_o' if cp_name=='cp_dummy_instr' else 'data_ind_timing_o'
                start=start & DNF.one(atom(self.f.c['seed_base']+'.cs_registers_i.'+signal,'==',[1]))
        if any(e['dom_kind']=='unresolved_implementation' for e in self.events):
            start=start & DNF.unknown()
        return self.checked(start)
