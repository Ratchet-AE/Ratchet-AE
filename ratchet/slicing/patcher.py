"""Recover original module/always shells; retain conditional skeletons."""
from .tracker import kind,parents,identifiers,tokens_estimate
import re
def patch(tracker,slice_result):
    selected=set(slice_result['statement_ids']);modules={tracker.statements[i].module for i in selected};chunks=[]
    if not hasattr(tracker,'_member_statement_ids'):
        from collections import defaultdict
        cache=defaultdict(list)
        for st in tracker.statements:
            for parent in parents(tracker.syntax[st.id]):
                if getattr(parent,'parent',None) is not None and kind(parent.parent) in ('ModuleDeclaration','InterfaceDeclaration'):
                    key=(st.module,kind(parent),parent.sourceRange.start.offset,parent.sourceRange.end.offset);cache[key].append(st.id);break
        tracker._member_statement_ids=cache
    for name in sorted(modules):
        info=tracker.modules[name];node=info['node'];needed=set();body=[]
        assignments={i:tracker.syntax[i] for i in selected if tracker.statements[i].module==name}
        for sid,n in assignments.items():
            needed.update(tracker.statements[sid].signals)
        for member in node.members:
            if not hasattr(member,'kind'):continue
            mk=kind(member)
            if mk in ('AlwaysBlock','AlwaysFFBlock','AlwaysCombBlock','AlwaysLatchBlock','ContinuousAssign'):
                allids=tracker._member_statement_ids.get((name,mk,member.sourceRange.start.offset,member.sourceRange.end.offset),[])
                if not selected.intersection(allids):continue
                text=str(member);needed.update(identifiers(member))
                # Replace complete expression statements, keeping if/case/begin/end.
                removals=[]
                for sid in allids:
                    if sid in selected:continue
                    n=tracker.syntax[sid];p=n.parent
                    if kind(p)=='ExpressionStatement':removals.append(str(p))
                for old in sorted(set(removals),key=len,reverse=True):text=text.replace(old,';\n// ...\n')
                body.append(text)
            elif mk=='HierarchyInstantiation':
                conns=[]
                def visit(c):
                    if 'PortConnection' in kind(c):
                        sid=next((i for i,n in tracker.syntax.items() if n is c),None)
                        if sid in selected:conns.append(str(c).strip())
                member.visit(visit)
                if conns:
                    needed.update(identifiers(member));body.append(str(member))
            elif mk in ('DataDeclaration','NetDeclaration','TypedefDeclaration','ParameterDeclaration','LocalParameterDeclaration','ImportDeclaration'):
                if mk=='ImportDeclaration' or set(tracker._declared(member))&needed:body.append(str(member))
        ports=[p['declaration'] for n,p in info['ports'].items() if n in needed]
        parameters=str(node.header.parameters) if node.header.parameters else ''
        header=f'module {name}{parameters} ('+', '.join(ports)+');'
        chunks.append(f'// Original: {info["file"]}\n'+header+'\n'+'\n'.join(body)+'\nendmodule\n')
    return slice_result['definitions']+'\n'+'\n'.join(chunks)
def filtered_slice(tracker,seeds,max_tokens=30000):
    target=getattr(seeds,'target',None)
    if target is not None and not seeds:
        from pathlib import Path
        if target['kind']=='line':
            path=Path(target['file']);line=min(target['lines'])
        else:
            from .tracker import X
            path=X/'third_party/ibex/dv/uvm/core_ibex/fcov/core_ibex_fcov_if.sv'
            source=path.read_text().splitlines();point=target['point']
            line=next((i+1 for i,v in enumerate(source) if re.search(r'\b'+re.escape(point)+r'\s*:',v)),1)
        rows=path.read_text().splitlines();text='// Source-window fallback: '+str(path)+':'+str(line)+'\n'+'\n'.join(rows[max(0,line-51):line+50])
        return dict(filtered_text=text,estimated_tokens=tokens_estimate(text),filtered_lines=len(text.splitlines()),truncated=False,source_fallback=True,file=str(path),line=line)
    budget=max_tokens
    while True:
        result=tracker.slice(seeds,budget);text=patch(tracker,result);cost=tokens_estimate(text)
        if cost<=max_tokens or not result['statement_ids']:
            result.update(filtered_text=text,estimated_tokens=cost,filtered_lines=len(text.splitlines()),truncated=result['truncated'] or budget<max_tokens);return result
        budget=max(0,int(budget*.75))
