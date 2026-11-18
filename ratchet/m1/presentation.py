"""Static display metadata for frozen M1 alternative conditions (no scoring)."""
from copy import deepcopy
from .front import strip,kind,const,refs,span,contains
from .contracts import enriched_guard
from .predicates import ast_expr
from ..m2.render import expression

def enum_members(f,signal):
 symbol=f.symbols.get(signal)
 if symbol is None:return {}
 typ=symbol.type.canonicalType
 if not typ.isEnum:return {}
 result={}
 for value in typ:
  try:number=int(value.value)
  except (TypeError,ValueError):number=int(value.value.value)
  result[str(number)]=value.name
 return result

def source_path(path):
 from pathlib import Path
 from .io import X
 try:return str(Path(path).resolve().relative_to(X.resolve()))
 except ValueError:
  resolved=Path(path).resolve()
  for root in ('duts','third_party'):
   marker='/'+root+'/'
   if marker in str(resolved):return root+'/'+str(resolved).split(marker,1)[1]
  return str(resolved)

def decision_guard(f,node,row):
 # Bound observers reference their containing RTL instance, not a child of
 # the observer itself. Filter by that physical parent to exclude lockstep
 # copies of the same source span; scoring's original guard code is untouched.
 scope=row['instance'].rsplit('.',1)[0]
 def same(expressions):return all(s.startswith(scope+'.') for c in expressions for s in refs(c))
 args=[]
 for location,cc,negative in f.conds_by_buffer[span(node)[0]]:
  if contains(location,span(node)) and same(cc):
   e=dict(kind='all',args=[ast_expr(c) for c in cc]);args.append(dict(kind='not',arg=e) if negative else e)
 for location,selector,values in f.cases_by_buffer[span(node)[0]]:
  if contains(location,span(node)) and values and same([selector,*values]):args.append(dict(kind='any',args=[dict(kind='compare',op='==',left=ast_expr(selector),right=ast_expr(v)) for v in values]))
 import json
 return dict(kind='all',args=list({json.dumps(e,sort_keys=True):e for e in args}.values())),[]

def enrich(f,conditions):
 for condition in conditions.values():
  signal=condition['signal'];values=condition['values'];names=enum_members(f,signal);display=deepcopy(condition['expr'])
  if names and display.get('kind')=='compare':
   if 'right' in display and str(display['right'].get('value')) in names:display['right']['display_name']=names[str(display['right']['value'])]
   if 'values' in display:display['display_values']=[names.get(str(v),str(v)) for v in display['values']]
  drivers=[]
  for node,row in f.ass.get(signal,[]):
   value=const(node.right)
   if value not in values:continue
   try:guard,gaps=decision_guard(f,node,row)
   except ValueError:continue
   if gaps:continue
   if const(node.right) is not None and getattr(strip(node.right),'symbol',None) is not None:
    label=getattr(strip(node.right).symbol,'name','')
   else:label=str(value)
   drivers.append(dict(predicate=guard,source=source_path(row['file'])+':'+str(row['line']),assignment=row['text'],enum_name=label))
  # Guards are the classification decision paths. Follow port aliases to the
  # first RTL equations for their controls, rather than printing sampled state.
  rtl=[];seen=set();pending=[(s,0) for d in drivers for s in sorted(refs_from_expr(d['predicate']))]
  while pending:
   s,depth=pending.pop()
   if s in seen or depth>2:continue
   seen.add(s)
   if s in f.portexpr:
    pending.extend((v,depth) for v in sorted(refs(f.portexpr[s])));continue
   if f.outports.get(s):pending.extend((v,depth) for v in f.outports[s]);continue
   for node,row in f.ass.get(s,[]):
    if row['sequential']:continue
    rhs=strip(node.right)
    if kind(rhs) in ('NamedValue','MemberAccess','HierarchicalValue'):
     pending.extend((v,depth) for v in sorted(refs(rhs)));continue
    if source_path(row['file']).startswith('third_party/'):
     entry=dict(source=source_path(row['file'])+':'+str(row['line']),text=' '.join(row['text'].split()))
     if entry not in rtl:rtl.append(entry)
    pending.extend((v,depth+1) for v in sorted(refs(rhs)))
  positive=set()
  def positives(e,neg=False):
   if e.get('kind')=='not':positives(e['arg'],not neg)
   elif e.get('kind')=='ref' and not neg:positive.add(e['path'].rsplit('.',1)[-1].removesuffix('_i').removesuffix('_o'))
   else:
    for v in e.values():
     if isinstance(v,dict):positives(v,neg)
     elif isinstance(v,list):
      for a in v:
       if isinstance(a,dict):positives(a,neg)
  for d in drivers:positives(d['predicate'])
  roots={v.rsplit('.',1)[-1].removesuffix('_i').removesuffix('_o') for d in drivers for v in refs_from_expr(d['predicate'])}
  def rank(d):
   lhs=d['text'].split('=')[0].strip().removesuffix('_o').removesuffix('_i')
   return 0 if lhs in positive else 1 if lhs in roots else 2
  rtl.sort(key=lambda d:(rank(d),d['source'].rsplit(':',1)[0],int(d['source'].rsplit(':',1)[1]),d['text']))
  condition['presentation']=dict(expression=display,enum_names=names,decision_paths=drivers,rtl_equations=rtl,derivation='M1 elaborated enum type, assignment guards and RTL control aliases; display-only')

def refs_from_expr(expr):
 from ..expressions import signals
 return signals(expr)
