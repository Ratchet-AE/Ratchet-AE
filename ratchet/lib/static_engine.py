"""Elaborated instance-aware, directed reverse sequential dependency analysis.

No simulation/model calls. Explicit AST self-reference is preserved; implicit
clock-enable holds are never synthesized. All structs/arrays are grouped only
when counting states, after member-sensitive dependency traversal.
"""
from pathlib import Path
from collections import defaultdict,deque
import pyslang as sl
import json,re,fnmatch

def kind(n):return str(getattr(n,'kind','')).split('.')[-1]

_argument_kinds=[name for name in sl.ast.SymbolKind.__members__ if name.endswith('Argument')]
if len(_argument_kinds)!=1:raise RuntimeError('Unsupported argument symbol kinds')
_ARGUMENT_KIND=_argument_kinds[0]

def refname(e):
    k=kind(e)
    if k in ('NamedValue','HierarchicalValue'):
        s=e.symbol
        if kind(s) not in ('Variable','Net',_ARGUMENT_KIND):return None
        return s.hierarchicalPath
    if k=='MemberAccess':
        b=refname(e.value)
        return b+'.'+e.member.name if b else None
    if k in ('ElementSelect','RangeSelect'):
        return refname(e.value)
    if k=='Conversion':return refname(e.operand)
    return None

def refs(e):
    if e is None:return set()
    out=set()
    def v(n):
        r=refname(n)
        if r:
            out.add(r)
            # Include an array index's dependencies, without splitting array
            # storage into element-sized states.
            if kind(n)=='ElementSelect':out.update(refs(n.selector))
            elif kind(n)=='RangeSelect':out.update(refs(n.left));out.update(refs(n.right))
            return sl.ast.VisitAction.Skip
    e.visit(v)
    return out

def lhsrefs(e):
    # Indices select a target, not additional targets.
    r=refname(e)
    if r:return {r}
    out=set()
    def v(n):
        q=refname(n)
        if q:out.add(q);return sl.ast.VisitAction.Skip
    e.visit(v);return out

def span(n):
    r=n.sourceRange
    return r.start.buffer.id,r.start.offset,r.end.offset

class Engine:
    def __init__(self,config):
        self.c=config;self.sm=sl.SourceManager()
        pp=sl.parsing.PreprocessorOptions();pp.additionalIncludePaths=config['include_dirs'];pp.predefines=config['defines']
        bag=sl.Bag();bag.preprocessorOptions=pp
        self.tree=sl.syntax.SyntaxTree.fromFiles(config['src_list'],self.sm,bag)
        errs=[str(d.code) for d in self.tree.diagnostics if d.isError()]
        if errs:raise RuntimeError('Syntax parsing errors '+str(errs[:10]))
        opts=sl.ast.CompilationOptions();opts.topModules={config['top']}|set(config.get('extra_top_modules',[]));opts.flags=sl.ast.CompilationFlags.DisableInstanceCaching;opts.paramOverrides=config.get('param_overrides',[])
        cb=sl.Bag();cb.compilationOptions=opts
        self.comp=sl.ast.Compilation(cb);self.comp.addSyntaxTree(self.tree)
        self.root=self.comp.getRoot()
        self.top=next(i for i in self.root.topInstances if i.name==config['top'])
        # Elaboration diagnostics are recorded; incomplete modules cannot be
        # silently treated as combinational wires.
        self.diagnostics=[]
        for d in self.comp.getAllDiagnostics():
            if d.isError():self.diagnostics.append(dict(code=str(d.code),file=str(self.sm.getFileName(d.location)),line=self.sm.getLineNumber(d.location),args=[str(a) for a in d.args]))
        self.instances={};self.symbols={};self.field_nodes=set();self.ports={};self.statements=[];self.reverse=defaultdict(set);self.driver_ids=defaultdict(set);self.regs=set();self.module_by_signal={}
        self.top.visit(self._visit)
        root=config.get('dut_root')
        if not root:
            candidates=[p for p,m in self.instances.items() if m==config['dut_module']]
            if len(candidates)!=1:raise RuntimeError('DUT instance root ambiguous: '+str(candidates))
            root=candidates[0]
        self.dut_root=root
        self.boundary={k for k,v in self.ports.items() if k.startswith(root+'.') and self._instance(k)==root and v=='In'}
        self.all_nodes=set(self.reverse)|{v for vals in self.reverse.values() for v in vals}|set(self.symbols)|self.field_nodes
        self.children=defaultdict(set)
        for n in self.all_nodes:
            parts=n.split('.')
            for i in range(1,len(parts)):self.children['.'.join(parts[:i])].add(n)
        self.class_cache={};self.cone_cache={};self.structure_cache={};self.reg_groups=defaultdict(set)
        for r in self.regs:self.reg_groups[self.structure(r)].add(r)
    def _instance(self,key):
        parts=key.split('.')
        for i in range(len(parts)-1,0,-1):
            p='.'.join(parts[:i])
            if p in self.instances:return p
        return ''
    def excluded(self,key):
        leaf=key.rsplit('.',1)[-1]
        return leaf.lower() in {n.lower() for n in self.c['exclude']}
    def in_dut(self,key):return key.startswith(self.dut_root+'.')
    def isboundary(self,key):return any(key==b or key.startswith(b+'.') for b in self.boundary)
    def _visit(self,n):
        k=kind(n)
        if k=='GenerateBlock' and n.isUninstantiated:return sl.ast.VisitAction.Skip
        if k=='Instance':
            self.instances[n.hierarchicalPath]=n.definition.name
            for pc in n.portConnections:
                p=pc.port;internal=refs(p.internalExpr) if p.internalExpr is not None else {p.internalSymbol.hierarchicalPath} if p.internalSymbol else set()
                external=refs(pc.expression)
                direction=str(p.direction).split('.')[-1]
                if direction in ('In','InOut'):
                    for a in internal:self.reverse[a].update(external)
                if direction in ('Out','InOut'):
                    for a in lhsrefs(pc.expression) if pc.expression is not None else []:self.reverse[a].update(internal)
        elif k in ('Variable','Net'):
            self.symbols[n.hierarchicalPath]=n
            self._type_fields(n.hierarchicalPath,n.type)
        elif k=='Port':
            self.ports[n.hierarchicalPath]=str(n.direction).split('.')[-1]
        elif k=='ProceduralBlock':
            self._process(n.body,n.hierarchicalPath,n.procedureKind)
            return sl.ast.VisitAction.Skip
        elif k=='ContinuousAssign':
            self._assignment(n.assignment,set(),False,n.hierarchicalPath)
            return sl.ast.VisitAction.Skip
        elif k in ('Subroutine','ClassType','Covergroup','GenerateBlock'):
            if k!='GenerateBlock':return sl.ast.VisitAction.Skip
    def _type_fields(self,path,typ,depth=0):
        if depth>12:return
        t=typ.canonicalType
        while t.isArray:t=t.elementType.canonicalType
        if t.isStruct or kind(t) in ('PackedUnionType','UnpackedUnionType'):
            for field in t:
                if not hasattr(field,'type'):continue
                key=path+'.'+field.name;self.field_nodes.add(key)
                self._type_fields(key,field.type,depth+1)
    def _process(self,body,path,proc_kind):
        controls=[];assigns=[];edge=False
        def scan(n):
            nonlocal edge
            k=kind(n)
            if k=='Assignment':assigns.append(n)
            elif k=='Conditional':
                dep=set()
                for c in n.conditions:dep.update(refs(c.expr))
                controls.append((span(n),dep))
            elif k in ('Case','PatternCase'):
                controls.append((span(n),refs(n.expr)))
            elif k in ('ForLoop','WhileLoop','DoWhileLoop','RepeatLoop'):
                dep=set()
                for attr in ['stopExpr','cond','count']:
                    if hasattr(n,attr):dep.update(refs(getattr(n,attr)))
                controls.append((span(n),dep))
            elif k=='SignalEvent' and str(n.edge).split('.')[-1] in ('PosEdge','NegEdge','BothEdges'):edge=True
        body.visit(scan)
        seq=str(proc_kind).split('.')[-1]=='AlwaysFF' or edge
        for a in assigns:
            b,s,e=span(a);dep=set()
            for (cb,cs,ce),ds in controls:
                if b==cb and cs<=s and e<=ce:dep.update(ds)
            self._assignment(a,dep,seq,path)
    def _assignment(self,a,control,seq,path):
        lhs=lhsrefs(a.left);rhs=refs(a.right)|control
        if a.isCompound:rhs.update(lhs)
        sr=a.sourceRange
        st=dict(lhs=sorted(lhs),rhs=sorted(rhs),sequential=seq,file=str(self.sm.getFileName(sr.start)),line=self.sm.getLineNumber(sr.start),module=self.instances.get(path,''),instance=path,text=str(a.syntax).strip())
        # Procedural symbols' hierarchicalPath can include named blocks. Find
        # the nearest real module instance, preserving generated instance paths.
        if not st['module']:
            ip=self._instance(next(iter(lhs),'') or path+'.dummy');st['instance']=ip;st['module']=self.instances.get(ip,'')
        sid=len(self.statements);self.statements.append(st)
        for key in lhs:
            self.reverse[key].update(rhs);self.driver_ids[key].add(sid)
            if seq:self.regs.add(key)
    def aliases(self,key):
        # An aggregate reference depends on drivers of its members; a member
        # reference also depends on whole-aggregate assignments/port aliases.
        found={key}
        found.update(n for n in self.children.get(key,()) if n in self.reverse)
        parts=key.split('.')
        for i in range(1,len(parts)):
            base='.'.join(parts[:i])
            if base in self.reverse:found.add(base)
        return found
    def predecessors(self,key):
        if self.isboundary(key):return set(),set()
        pred=set();ids=set()
        for a in self.aliases(key):
            for n in self.reverse.get(a,()):
                suffix=key[len(a):] if key.startswith(a+'.') else ''
                projected=n+suffix
                pred.add(projected if suffix and (projected in self.all_nodes or projected in self.children) else n)
            ids.update(self.driver_ids.get(a,()))
        return pred,ids
    def regkeys(self,key):
        return {a for a in self.aliases(key) if a in self.regs}
    def structure(self,key):
        # Array elements already share refname. Struct fields share the base
        # variable in one module instance; q/d spelling has a canonical q name.
        if key in self.structure_cache:return self.structure_cache[key]
        parts=key.split('.');base=key
        for i in range(len(parts),0,-1):
            p='.'.join(parts[:i])
            if p in self.symbols:base=p;break
        if base.endswith('_d'):base=base[:-2]+'_q'
        self.structure_cache[key]=base
        return base
    def dcone(self,key):
        if key in self.cone_cache:return self.cone_cache[key]
        start=set()
        for sid in self.driver_ids.get(key,()):
            s=self.statements[sid]
            if s['sequential']:start.update(s['rhs'])
        queue=deque(start);seen=set();registers=set()
        while queue:
            n=queue.popleft()
            if n in seen or self.excluded(n) or not self.in_dut(n):continue
            seen.add(n)
            rs=self.regkeys(n)
            if rs:registers.update(rs);continue
            if self.isboundary(n):continue
            pre,_=self.predecessors(n);queue.extend(pre)
        self.cone_cache[key]=(seen,registers)
        return seen,registers
    def classify(self,key):
        st=self.structure(key)
        if st in self.class_cache:return self.class_cache[st]
        members=self.reg_groups.get(st,());seen=set();r=set()
        for k in members:
            ss,rr=self.dcone(k);seen.update(ss);r.update(rr)
        instance=self._instance(st)
        direct=any(fnmatch.fnmatch(instance,p) for p in self.c['direct_patterns']) and any(any(n==b or n.endswith('.'+b) for b in self.c['bus_wdata']) for n in seen)
        accum=any(self.structure(k)==st for k in r)
        value='direct' if direct else 'accum' if accum else 'plain'
        self.class_cache[st]=value
        return value
    def resolve(self,expression,base=None):
        base=base or self.c.get('seed_base',self.dut_root);out=set();missing=[]
        # Explicit source-model mapping lists signal paths; arbitrary guessing
        # and source-window fallback never count as a resolved seed.
        for token in expression:
            key=token if token.startswith(self.dut_root+'.') else base+'.'+token
            if key in self.all_nodes or key in self.children:out.add(key)
            else:missing.append(token)
        return sorted(out),missing
    def slice(self,seeds):
        q=deque((s,0) for s in seeds);depths={};states=set();modules=set();trunc=False
        while q:
            key,depth=q.popleft()
            if key in depths and depths[key]<=depth or self.excluded(key) or not self.in_dut(key):continue
            depths[key]=depth
            if self.isboundary(key):continue
            rs=self.regkeys(key)
            # Register count is in structures, not bits or array elements.
            for r in rs:states.add(self.structure(r))
            if len(states)>self.c['max_registers']:
                trunc=True;break
            pre,ids=self.predecessors(key)
            for sid in ids:
                m=self.statements[sid]['module']
                if m:modules.add(m)
            if rs:
                if depth+1>=self.c['max_reg_depth']:
                    trunc=True;continue
                depth+=1
            for n in sorted(pre):q.append((n,depth))
        accum=sorted(s for s in states if self.classify(s)=='accum')
        return dict(n_accum=len(accum),n_modules=len(modules),truncated=int(trunc),accum_structures=accum,modules=sorted(modules),visited_signals=len(depths))
    def summary(self):
        return dict(dut=self.c['dut'],root=self.dut_root,instances=len(self.instances),statements=len(self.statements),register_signals=len(self.regs),diagnostics=self.diagnostics)

    def save(self,path):
        data=dict(config=self.c,instances=self.instances,symbols=list(self.symbols),field_nodes=sorted(self.field_nodes),ports=self.ports,statements=self.statements,reverse={k:sorted(v) for k,v in self.reverse.items()},driver_ids={k:sorted(v) for k,v in self.driver_ids.items()},regs=sorted(self.regs),dut_root=self.dut_root,boundary=sorted(self.boundary),diagnostics=self.diagnostics)
        Path(path).write_text(json.dumps(data,separators=(',',':'))+'\n')
    @classmethod
    def restore(cls,path):
        d=json.loads(Path(path).read_text());e=cls.__new__(cls)
        e.field_nodes=set(d.get('field_nodes',[]));e.c=d['config'];e.instances=d['instances'];e.symbols={k:None for k in d['symbols']};e.ports=d['ports'];e.statements=d['statements'];e.reverse=defaultdict(set,{k:set(v) for k,v in d['reverse'].items()});e.driver_ids=defaultdict(set,{k:set(v) for k,v in d['driver_ids'].items()});e.regs=set(d['regs']);e.dut_root=d['dut_root'];e.boundary=set(d['boundary']);e.diagnostics=d['diagnostics'];e.class_cache={};e.cone_cache={};e.structure_cache={};e.reg_groups=defaultdict(set)
        e.all_nodes=set(e.reverse)|{v for vals in e.reverse.values() for v in vals}|set(e.symbols)|e.field_nodes
        e.children=defaultdict(set)
        for n in e.all_nodes:
            parts=n.split('.')
            for i in range(1,len(parts)):e.children['.'.join(parts[:i])].add(n)
        for r in e.regs:e.reg_groups[e.structure(r)].add(r)
        return e
