"""UVMarvel undirected signal/statement BFS over pyslang syntax ASTs.

Vertices use module-definition-qualified names; instances are traversed through
parameter/actual ports with global visited. Reused module definitions are deliberately
shared (conservative overapproximation), never inferred as a dynamic execution.
"""
from pathlib import Path
from dataclasses import dataclass,field,asdict
from collections import defaultdict,deque
import shlex,re,json,math
import pyslang as slang
X=Path(__file__).resolve().parents[2]
ASSIGN={'AssignmentExpression','NonblockingAssignmentExpression','AddAssignmentExpression','SubtractAssignmentExpression'}
def kind(n):return str(n.kind).split('.')[-1]
def identifiers(node):
    result=set()
    if node is None:return result
    def visit(n):
        if kind(n) in ('IdentifierName','IdentifierSelectName'):result.add(n.identifier.valueText)
    node.visit(visit);return result
def parents(node):
    p=getattr(node,'parent',None)
    while p is not None:yield p;p=p.parent
def module_of(node):
    for p in [node,*parents(node)]:
        if kind(p) in ('ModuleDeclaration','InterfaceDeclaration','ProgramDeclaration'):return p.header.name.valueText
    return None
def tokens_estimate(text):
    import tiktoken
    return len(tiktoken.get_encoding('o200k_base').encode(text))
@dataclass
class Statement:
    id:int;module:str;file:str;start:int;end:int;line:int;end_line:int;text:str
    signals:list;lhs:list;rhs:list;conditions:list;sequential:bool;kind:str
    case_expr:str='';case_labels:list=field(default_factory=list)
    def public(self):return asdict(self)
class Tracker:
    def __init__(self,paths,include_dirs=(),defines=(),exclude=()):
        self.paths=[str(Path(p).resolve()) for p in paths];self.exclude=set(exclude);self.exclude_lower={n.lower() for n in self.exclude}
        pp=slang.parsing.PreprocessorOptions();pp.additionalIncludePaths=list(include_dirs);pp.predefines=list(defines)
        options=slang.Bag();options.preprocessorOptions=pp;self.sm=slang.SourceManager()
        self.tree=slang.syntax.SyntaxTree.fromFiles(self.paths,self.sm,options)
        self.diagnostics=[dict(code=str(d.code),file=str(self.sm.getFileName(d.location)),line=self.sm.getLineNumber(d.location),error=d.isError(),args=[str(a) for a in d.args]) for d in self.tree.diagnostics]
        errors=[d for d in self.diagnostics if d['error']]
        if errors:raise ValueError('pyslang syntax errors: '+json.dumps(errors[:10]))
        self.modules={};self.statements=[];self.index=defaultdict(set);self.links=defaultdict(set);self.reverse_links=defaultdict(set);self.definitions=[];self.syntax={};self.connections=[];self.constants=set()
        self.tree.root.visit(self._collect_module)
        self.tree.root.visit(self._collect_statement)
        self._ports()
        self.drivers=defaultdict(list)
        for st in self.statements:
            for name in st.lhs:self.drivers[(st.module,name)].append(st.id)
    def _location(self,n):
        r=n.sourceRange
        return str(self.sm.getFileName(r.start)),r.start.offset,r.end.offset,self.sm.getLineNumber(r.start),self.sm.getLineNumber(r.end)
    def _collect_module(self,n):
        k=kind(n)
        if k in ('ModuleDeclaration','InterfaceDeclaration','ProgramDeclaration'):
            name=n.header.name.valueText
            if name in self.modules:return
            ports={};previous='input logic'
            if n.header.ports is not None:
                for port in n.header.ports.ports:
                    if not hasattr(port,'declarator'):continue
                    h=str(port.header).strip()
                    if h:previous=h
                    pname=port.declarator.name.valueText
                    ports[pname]=dict(declaration=previous+' '+str(port.declarator).strip(),direction=previous.split()[0])
            self.modules[name]=dict(node=n,ports=ports,file=self._location(n)[0],header=str(n.header),text=str(n))
        if k in ('TypedefDeclaration','ParameterDeclaration','LocalParameterDeclaration'):
            text=str(n).rstrip()
            if not text.endswith(';'):text+='\n;'
            self.definitions.append(dict(module=module_of(n),text=text,file=self._location(n)[0],line=self._location(n)[3],names=self._declared(n)))
            if 'Parameter' in k:self.constants.update(self._declared(n))
        if k=='EnumType':
            for m in n.members:
                if hasattr(m,'name'):self.constants.add(m.name.valueText)
    def _declared(self,n):
        names=[]
        def v(c):
            if kind(c)=='Declarator':names.append(c.name.valueText)
        n.visit(v)
        if hasattr(n,'name'):names.append(n.name.valueText)
        return names
    def _collect_statement(self,n):
        k=kind(n)
        if k not in ASSIGN and k not in ('NamedPortConnection','OrderedPortConnection'):return
        module=module_of(n)
        if not module:return
        if k in ASSIGN:
            if any(kind(p) in ASSIGN for p in parents(n)):return
            if any(kind(p) in ('ForLoopStatement','ForVariableDeclaration','ForInitializer') for p in parents(n)):
                # Loop initializers/steps are procedural control, not flops.
                if any(kind(p) in ('ForVariableDeclaration','ForInitializer') for p in parents(n)):return
            lhs=identifiers(n.left);rhs=identifiers(n.right);conditions=[];sequential=False;case_expr='';case_labels=[]
            for p in parents(n):
                pk=kind(p)
                if pk=='ConditionalStatement':conditions.append(str(p.predicate))
                if pk=='CaseStatement':case_expr=str(p.expr);conditions.append(case_expr)
                if pk in ('StandardCaseItem','DefaultCaseItem') and hasattr(p,'expressions'):case_labels += [re.sub(r'/\*.*?\*/|//[^\n]*','',str(x),flags=re.S).strip() for x in p.expressions if str(getattr(x,'kind','')).startswith('SyntaxKind.')]
                if pk=='AlwaysFFBlock' or pk=='AlwaysBlock' and 'posedge' in str(p.statement)[:150]:sequential=True
                if pk in ('ModuleDeclaration','InterfaceDeclaration'):break
            seq=sequential or k=='NonblockingAssignmentExpression'
            signals=set(lhs)|rhs
            for p in parents(n):
                if kind(p)=='ConditionalStatement':signals.update(identifiers(p.predicate))
                if kind(p)=='CaseStatement':signals.update(identifiers(p.expr))
                if kind(p)=='TimingControlStatement':signals.update(identifiers(p.timingControl))
            self._add(n,module,k,lhs,rhs,signals,conditions,seq,case_expr,case_labels)
        elif k in ('NamedPortConnection','OrderedPortConnection'):
            inst=next((p for p in parents(n) if kind(p)=='HierarchyInstantiation'),None)
            if inst is None:return
            actual=identifiers(n.expr) if hasattr(n,'expr') else set()
            parameter=n.name.valueText if hasattr(n,'name') else None
            hierarchical=next((p for p in parents(n) if kind(p)=='HierarchicalInstance'),None)
            sid=self._add(n,module,'port',set(),actual,actual,[],False)
            self.connections.append((sid,module,str(inst.type).strip(),parameter,actual,hierarchical))
    def _add(self,n,module,k,lhs,rhs,signals,conditions,seq,case_expr='',case_labels=None):
        signals=set(signals)-self.constants
        f,start,end,line,end_line=self._location(n);sid=len(self.statements)
        st=Statement(sid,module,f,start,end,line,end_line,str(n),sorted(signals),sorted(lhs),sorted(rhs),conditions,seq,k,case_expr,case_labels or [])
        self.statements.append(st);self.syntax[sid]=n
        for name in signals:
            if not self.excluded(name):self.index[(module,name)].add(sid)
        return sid
    def excluded(self,name):return name.lower() in self.exclude_lower
    def _ports(self):
        for sid,parent,child,parameter,actual,instance in self.connections:
            if child not in self.modules:continue
            if parameter is None and instance is not None:
                cons=[c for c in instance.connections if hasattr(c,'kind') and 'PortConnection' in kind(c)]
                try:parameter=list(self.modules[child]['ports'])[cons.index(self.syntax[sid])]
                except (ValueError,IndexError):continue
            if not parameter or self.excluded(parameter):continue
            direction=self.modules[child]['ports'].get(parameter,{}).get('direction','inout')
            parameter_key=(child,parameter);self.index[parameter_key].add(sid)
            for name in actual:
                if self.excluded(name):continue
                actualkey=(parent,name);self.links[actualkey].add(parameter_key);self.links[parameter_key].add(actualkey)
                # reverse graph maps a driven vertex to its driver.
                if direction in ('input','inout'):self.reverse_links[parameter_key].add(actualkey)
                if direction in ('output','inout'):self.reverse_links[actualkey].add(parameter_key)
    @classmethod
    def for_dut(cls,dut):
        if dut=='sd':paths=[X/'third_party/ml4dv/stride_detector/stride_detector.sv',X/'duts/sd/tb/xb_sd.sv'];inc=[];defines=['VERILATOR=1']
        else:
            args=shlex.split((X/f'duts/{dut}/tb/rtl_absolute.f').read_text());paths=[a for a in args if a.endswith(('.v','.sv'))];inc=[a[len('+incdir+'):] for a in args if a.startswith('+incdir+')];defines=['VERILATOR=1']+[a[2:] for a in args if a.startswith('-D')]
        exclude=(X/f'methods/uvmb/tracker_exclude_{dut}.txt').read_text().split()
        result=cls(paths,inc,defines,exclude);result.dut=dut
        comp=slang.ast.Compilation();comp.addSyntaxTree(result.tree);root=comp.getRoot()
        name={'sd':'xb_sd','es':'xb_es','ibex':'ibex_simple_system'}[dut]
        top=next(t for t in root.topInstances if t.name==name);active=set();registers=set()
        def visit(symbol):
            if str(symbol.kind)=='SymbolKind.InstanceBody':active.add(symbol.definition.name)
            if str(symbol.kind)=='SymbolKind.Variable' and symbol.declaringDefinition is not None and not symbol.parentScope.isProceduralContext and not symbol.parentScope.isUninstantiated:registers.add((symbol.declaringDefinition.name,symbol.name))
        top.visit(visit);result.active_modules=active;result.active_registers=registers;result.compilation=comp;result.elaborated_top=top
        result.index=defaultdict(set,{k:v for k,v in result.index.items() if k[0] in active})
        result.links=defaultdict(set,{k:{v for v in values if v[0] in active} for k,values in result.links.items() if k[0] in active})
        result.reverse_links=defaultdict(set,{k:{v for v in values if v[0] in active} for k,values in result.reverse_links.items() if k[0] in active})
        return result
    def resolve(self,names,module=None):
        found=[]
        for name in names:
            if isinstance(name,(list,tuple)):key=tuple(name);found.extend([key] if key in self.index else []);continue
            if '.' in name:
                m,n=name.rsplit('.',1)
                if (m,n) in self.index:found.append((m,n));continue
            found += [k for k in self.index if k[1]==name and (module is None or k[0]==module)]
        return sorted(set(found))
    def slice(self,seeds,max_tokens=30000):
        queue=deque((tuple(k),0) for k in seeds);visited=set();selected=set();layers=defaultdict(list);truncated=False
        while queue:
            key,depth=queue.popleft()
            if key in visited or self.excluded(key[1]):continue
            visited.add(key)
            for sid in sorted(self.index.get(key,())):
                if sid in selected:continue
                selected.add(sid);layers[depth].append(sid)
                s=self.statements[sid]
                for n in s.signals:
                    if not self.excluded(n):queue.append(((s.module,n),depth+1))
            for other in sorted(self.links.get(key,())):queue.append((other,depth+1))
        kept=[];used=0
        for depth,ids in sorted(layers.items()):
            text='\n'.join(self.statements[i].text for i in ids);cost=tokens_estimate(text)
            if used+cost>max_tokens:truncated=True;break
            kept+=ids;used+=cost
        definitions=self.required_definitions(kept)
        while kept and tokens_estimate('\n'.join(self.statements[i].text for i in kept)+'\n'+definitions)>max_tokens:
            lastdepth=max(d for d,ids in layers.items() if set(ids)&set(kept));kept=[i for i in kept if i not in layers[lastdepth]];truncated=True;definitions=self.required_definitions(kept)
        lines={(self.statements[i].file,l) for i in kept for l in range(self.statements[i].line,self.statements[i].end_line+1)}
        return dict(statement_ids=sorted(kept),statements=[self.statements[i].public() for i in sorted(kept)],definitions=definitions,slice_lines=len(lines),estimated_tokens=tokens_estimate('\n'.join(self.statements[i].text for i in kept)+'\n'+definitions),truncated=truncated,seeds=[list(k) for k in seeds],visited_signals=len(visited),bfs_layers=len(layers))
    def required_definitions(self,ids):
        used=set(re.findall(r'\b[A-Za-z_]\w*\b','\n'.join(self.statements[i].text for i in ids)));chosen=[];seen=set()
        if not hasattr(self,'_definition_dependencies'):
            self._definition_dependencies=[set(re.findall(r'\b[A-Za-z_]\w*\b',d['text'])) for d in self.definitions]
        for _ in range(8):
            changed=False
            for idx,d in enumerate(self.definitions):
                if idx not in seen and set(d['names'])&used:
                    seen.add(idx);chosen.append(d['text']);used.update(self._definition_dependencies[idx]);changed=True
            if not changed:break
        return '\n'.join(chosen)
