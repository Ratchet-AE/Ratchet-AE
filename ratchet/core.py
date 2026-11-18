"""Policy, predicate-keyed archives and bounded diagnosis."""
import hashlib,json,math,time
from collections import defaultdict
import tiktoken
ENC=tiktoken.get_encoding('o200k_base')
PARAMS=dict(C0=10180,tau=10,N=4,L_min=200,L_max=2000,K_stall=3,D_max=1500,R_max=6,rho=.20)
def count(text):return len(ENC.encode(text))
def reservation(request,schema,outputs):
 output=math.ceil(max(outputs)*1.2) if outputs else 8000
 return dict(input_estimate=count(request)+count(schema)+10180,output_reserve=output,total=count(request)+count(schema)+10180+output)
def cp_key(cp):return json.dumps({k:v for k,v in cp.items() if k not in ('pattern',)},sort_keys=True)
def priority(target,frontier,ncp):return len(target.get('bins',target.get('lines',[])))*(frontier+1)/(ncp+1)
class Policy:
 def __init__(self,method):self.method=method;self.gains=[];self.upgraded=False;self.dry=0;self.stalls=defaultdict(int);self.excluded=set();self.tier0_insert=False
 def tier0(self,gain):
  self.gains.append(gain)
  if self.method!='r_t0' and len(self.gains)>=2 and max(self.gains[-2:])<PARAMS['tau']:self.upgraded=True
 def upgraded_call(self,target,old,new,gain):
  self.stalls[target]=self.stalls[target]+1 if new<=old else 0
  self.dry=self.dry+1 if gain==0 else 0
  self.tier0_insert=self.dry>=3
  if self.tier0_insert:self.dry=0
  return self.stalls[target]>=3
class Archives:
 def __init__(self,event=lambda *a,**k:None):self.entries=defaultdict(list);self.used=defaultdict(set);self.event=event
 def add(self,cp,prefix,state,target,test):
  key=cp_key(cp);regs=[cp['register']]
  if 'threshold_register' in cp:regs.append(cp['threshold_register'])
  from ratchet.components.m2_diag import value
  signature=json.dumps([value(state,r) for r in regs]);entries=self.entries[key]
  if any(e['signature']==signature for e in entries) or len(entries)>=3:return False
  entry=dict(prefix=list(prefix),state={'.'.join(r):value(state,r) for r in regs},signature=signature,owner=target,test=test)
  entries.append(entry);self.event('archive_saved',target=target,predicate=key,prefix_len=len(prefix),source_test=test);return True
 def choose(self,chain,target,max_frontier=None):
  upper=len(chain)-1 if max_frontier is None else min(max_frontier,len(chain)-1)
  for idx in range(upper,-1,-1):
   key=cp_key(chain[idx])
   for slot,e in enumerate(self.entries[key]):
    if (key,slot) not in self.used[target] and len(e['prefix'])<=1800:
     if e['owner']!=target:self.event('archive_shared',target=target,owner=e['owner'],predicate=key)
     return idx,key,slot,e
  return -1,None,None,dict(prefix=[],state={})
 def reject(self,target,selection):
  idx,key,slot,_=selection
  if key is not None:self.used[target].add((key,slot))
  return self.choose([],target) if key is None else None
def compact(diag,confirmation=None):
 lines=[f"frontier={diag.get('frontier',-1)}",f"peak={diag.get('progress_peak')}"]
 if confirmation:lines.append('top_regression='+json.dumps(confirmation,ensure_ascii=False))
 else:lines.append('top_regression=unconfirmed')
 output=[]
 for line in lines:
  # Truncate at token boundary, not an assumed character ratio.
  remaining=1500-count('\n'.join(output))
  if remaining<=1:break
  output.append(ENC.decode(ENC.encode(line)[:remaining-1]))
 return '\n'.join(output)
def one_loss(trace,chain,diagnostic):
 from ratchet.components.m2_diag import snapshots,predicate
 rows=list(snapshots(trace));enums=trace[0].get('_enums',{}) if trace else {};frontier=diagnostic.get('frontier',-1)
 if frontier<0:return None
 previous=False
 for row in rows:
  now=all(predicate(c,row['state'],enums) for c in chain[:frontier+1])
  if previous and not now:
   candidates=[e for e in diagnostic['regressions'] if e['index']==row['index'] and e['checkpoint']<=frontier]
   if candidates:return candidates[0]
  previous=now
 return None
class Bisector:
 def __init__(self,run,wall_seconds=3600,event=lambda *a,**k:None):self.run=run;self.limit=wall_seconds*.2;self.elapsed=0.;self.cache={};self.event=event;self.n=0;self.deadline=time.time()+wall_seconds
 def confirm(self,test,event,replay):
  if not event:return dict(confirmed=False,reason='no_frontier_loss',replays=0)
  window=list(range(max(0,event['index']-8),event['index']+1));used=0
  prefix=test['inputs'][:event['index']+1];digest=hashlib.sha256(json.dumps(prefix).encode()).hexdigest()
  def query(removed):
   nonlocal used
   key=(digest,tuple(removed))
   signature=(event['checkpoint'],event['previous'],event['current'])
   if key in self.cache and signature in self.cache[key]:return self.cache[key][signature]
   if used>=6 or self.elapsed>=self.limit or time.time()>=self.deadline-2:return None
   tick=time.monotonic();answer,sim_s=replay(removed,event,self.limit-self.elapsed);self.elapsed+=sim_s;self.n+=1;used+=1
   self.cache.setdefault(key,{})[signature]=answer;self.event('cf_replay',removed=list(removed),gone=answer,t_sim_s=sim_s,prefix_hash=digest,event_index=event['index']);return answer
  while len(window)>1 and used<5:
   half=window[len(window)//2:];answer=query(half)
   if answer is None:return dict(confirmed=False,reason='time_or_replay_budget',replays=used)
   window=half if answer else window[:len(window)//2]
  answer=query(window)
  return dict(confirmed=answer is True,removed_index=window[0] if answer else None,reason=event['reason'] if answer else 'unconfirmed',replays=used)
