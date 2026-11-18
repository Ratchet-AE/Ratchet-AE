"""Label-closed archive cuts and name-only fragment isolation."""
from ratchet.utils.workspace import Workspace
import re,hashlib,tempfile
from functools import lru_cache
TOKEN=re.compile(r'"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|/\*.*?\*/|\#[^\n]*|//[^\n]*|[A-Za-z_.$][\w.$]*|[0-9][A-Za-z0-9_]*|:',re.S)
def tokens(text):
 return [(m.group(),m.start(),m.end()) for m in TOKEN.finditer(text) if not m.group().startswith(('"',"'",'#','//','/*'))]
def definitions(text):
 ts=tokens(text);defs=[]
 for i,(name,a,b) in enumerate(ts):
  if i+1<len(ts) and ts[i+1][0]==':' and re.fullmatch(r'(?:\d+|[A-Za-z_.$][\w.$]*)',name):defs.append((name,a,b))
  if name in ('.equ','.equiv','.set') and i+1<len(ts):defs.append(ts[i+1])
 return defs
def references(text,universe=()):
 ds=definitions(text);positions={a for _,a,b in ds};names={n for n,a,b in ds if not n.isdigit()}|set(universe);out=[]
 for name,a,b in tokens(text):
  if a in positions:continue
  if re.fullmatch(r'\d+[fb]',name) or name in names:out.append((name,a,b))
 return out
def unresolved(text,universe=()):
 ds=definitions(text);out=[];ordinary={n for n,a,b in ds if not n.isdigit()}
 for name,a,b in references(text,universe):
  if re.fullmatch(r'\d+[fb]',name):
   number,direction=name[:-1],name[-1];targets=[p for n,p,q in ds if n==number and (p>a if direction=='f' else p<a)]
   if not targets:out.append(name)
  elif name not in ordinary:out.append(name)
 return sorted(set(out))
@lru_cache(maxsize=8192)
def closed_cut(text,index):
 from ..sched.replay import safe_prefix_cut
 lines=text.splitlines(keepends=True);universe={n for n,a,b in definitions(text) if not n.isdigit()};cut=min(index,len(lines))
 while cut>0:
  balanced=safe_prefix_cut(lines,cut)
  if balanced!=cut:cut=balanced;continue
  if not unresolved(''.join(lines[:cut]),universe):break
  cut-=1
 return cut
def namespace(text,prefix,fallback=None):
 ds=definitions(text);occupied={n for n,a,b in ds};stem='ratchet_'+prefix+'_'
 while any(n.startswith(stem) for n in occupied):stem='z_'+stem
 mapping={};replacements=[];numbers={}
 for name,a,b in ds:
  if name.isdigit():
   ordinal=len(numbers.setdefault(name,[]));renamed=stem+name+'_'+str(ordinal);numbers[name].append((a,renamed));replacements.append((a,b,renamed))
  else:mapping.setdefault(name,stem+'n_'+name.encode().hex())
 # Ordinary names are isolated too; suffix references to a prefix symbol are
 # resolved only when the suffix does not define its own symbol of that name.
 defpos={a for n,a,b in ds if n.isdigit()}
 for name,a,b in tokens(text):
  if a in defpos:continue
  if re.fullmatch(r'\d+[fb]',name):
   candidates=[(p,n) for p,n in numbers.get(name[:-1],[]) if (p>a if name[-1]=='f' else p<a)]
   target=(min(candidates) if name[-1]=='f' else max(candidates))[1] if candidates else stem+'undefined_'+name
   replacements.append((a,b,target))
  elif name in mapping or name in (fallback or {}):replacements.append((a,b,mapping.get(name,(fallback or {}).get(name))))
 for a,b,name in sorted(replacements,reverse=True):text=text[:a]+name+text[b:]
 return text,mapping
def expand_repeats(text):
 lines=text.splitlines(keepends=True);out=[];i=0
 while i<len(lines):
  match=re.match(r'\s*\.rept\s+(0[xX][0-9a-fA-F]+|[0-9]+)\s*(?:[#].*)?$',lines[i].rstrip())
  if not match:out.append(lines[i]);i+=1;continue
  depth=1;j=i+1
  while j<len(lines) and depth:
   op=lines[j].strip().split()
   if op and op[0] in ('.rept','.irp','.irpc'):depth+=1
   if op and op[0]=='.endr':depth-=1
   j+=1
  if depth:raise ValueError('unclosed assembler repeat block')
  count=int(match.group(1),0) if match.group(1).lower().startswith('0x') else int(match.group(1))
  if count>100000:raise ValueError('repeat too large for safe label isolation')
  body=expand_repeats(''.join(lines[i+1:j-1]));out.extend([body]*count);i=j
 return ''.join(out)
def join(prefix,suffix):
 p,ordinary=namespace(expand_repeats(''.join(prefix)),'p');s,_=namespace(expand_repeats(suffix),'s',ordinary)
 return p+('\n' if p and not p.endswith('\n') else '')+s
@lru_cache(maxsize=8192)
def assemble_prefix(text):
 from tb.dsl.ibex import to_driver
 from tb.dsl.common import CompileError,ParseError
 try:
  isolated=join(text.splitlines(keepends=True),'')
  with Workspace(prefix='ratchet-archive-asm-') as d:to_driver(dict(rationale='Archive assembly-only validation; no simulation/model/coverage',asm=isolated or '# empty prefix; fixed tohost epilogue only\n'),d)
  return dict(passed=True,prefix_sha256=hashlib.sha256(text.encode()).hexdigest())
 except (CompileError,ParseError,ValueError) as e:return dict(passed=False,prefix_sha256=hashlib.sha256(text.encode()).hexdigest(),reason=str(e))
def checked_cut(lines,index):
 text=''.join(lines);cut=closed_cut(text,index);result=assemble_prefix(''.join(lines[:cut]))
 if result['passed']:return cut,result,[]
 return None,result,[dict(index=cut-1,**result)]
