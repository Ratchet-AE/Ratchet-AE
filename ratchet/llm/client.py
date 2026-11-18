"""One client and locked generator quota across calibrations and methods."""
from pathlib import Path
from dataclasses import dataclass
from ratchet.paths import REPO_ROOT
import csv,fcntl,json,os,time
import yaml
X=REPO_ROOT
PREFIX='Answer using only this request. Do not read files or run commands.'
class EmergencyStop(RuntimeError):pass
STOP=None
class BudgetExhausted(RuntimeError):pass
class QuotaCapReached(RuntimeError):pass
@dataclass
class CallResult:
 ok:bool
 parsed:dict|None
 raw_text:str
 usage:dict
 contaminated:bool
 t_s:float
 meta:dict

def call_llm(run_dir,call_id,purpose,request_text,schema_path,*,dry_run=False):
 run_dir=Path(run_dir);run_dir.mkdir(parents=True,exist_ok=True);lock=(run_dir/'quota.lock').open('w')
 STOP=run_dir/'stop.json'
 # Serialization is deliberately <=2 concurrent requests; quota decision atomic.
 with lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if STOP.exists():raise EmergencyStop('Stage3 safety stop is active; user decision required')
  cfg=yaml.safe_load((X/'configs/accounting.yaml').read_text());qpath=run_dir/'quota.json';q=json.loads(qpath.read_text()) if qpath.exists() else dict(raw_tokens_accounted=0,raw_tokens_known=0,n_calls=0,n_unknown=0,rate_limit_evidence=[],calls=[]);bpath=run_dir/'budget.json';budget=json.loads(bpath.read_text()) if bpath.exists() else dict(n_calls=0,raw_tokens_accounted=0,t_model_s=0,start_unix=time.time())
  if cfg['stage']==2:raise RuntimeError('Stage2 has no authorized model calls; stop and ask the user')
  if q['raw_tokens_accounted']>=cfg['global_token_cap'] or (cfg['stage']==0 and q['n_calls']>=3):raise QuotaCapReached('Global stage quota exhausted; no new request started')
  if budget['raw_tokens_accounted']>=cfg['per_run_token_cap'] or time.time()-budget['start_unix']>=cfg['per_run_wall_seconds']:raise BudgetExhausted('Run token or wall budget exhausted')
  if cfg.get('reservation_gate',False):
   from ratchet.core import reservation
   outputs=[u['output_tokens'] for c in q['calls'] if c['run_dir']==str(run_dir) for u in c.get('usage_raw',[]) if 'output_tokens' in u]
   reserve=reservation(PREFIX+'\n'+request_text,Path(schema_path).read_text(),outputs)
   decision=dict(call_id=call_id,used_run=budget['raw_tokens_accounted'],used_global=q['raw_tokens_accounted'],**reserve)
   with (run_dir/'reservations.jsonl').open('a') as f:f.write(json.dumps(decision)+'\n')
   if budget['raw_tokens_accounted']+reserve['total']>cfg['per_run_token_cap']:raise BudgetExhausted('Reservation gate: next request exceeds run cap')
   if q['raw_tokens_accounted']+reserve['total']>cfg['global_token_cap']:raise QuotaCapReached('Reservation gate: next request exceeds global cap')
  from ratchet.llm.api_client import call
  meta=call(PREFIX+'\n'+request_text,json.loads(Path(schema_path).read_text()),run_dir,call_id,purpose,dry_run=dry_run)
  croot=run_dir/'calls'/call_id;u=meta['usage_raw'][0] if meta['usage_known'] else {}
  if u.get('cached_input_tokens',0)>0:
   with (run_dir/'run.log').open('a') as log:log.write(f"WARNING {call_id}: cached_input > 0; reconfirm whether cached tokens are included in input; budget remains input+output.\n")
   note='\nCache warning: cached_input > 0 observed; Confirm whether cached tokens are included in input.Budget remains input + output.\n'
   with (run_dir/'run.log').open('a') as log:log.write(note)
  raw=u.get('input_tokens',0)+u.get('output_tokens',0) if meta['usage_known'] else None
  known=[v['raw_tokens'] for v in q['calls'] if v.get('raw_tokens') is not None]
  account=raw if raw is not None else sum(known)/len(known) if known else cfg['initial_unknown_reserve_tokens']
  record=dict(run_dir=str(run_dir),call_id=call_id,purpose=purpose,started=meta['started'],raw_tokens=raw,accounted_tokens=account,usage_known=meta['usage_known'],contaminated=meta['contaminated'],usage_raw=meta['usage_raw'],n_reconnect=meta['n_reconnect'],transport_failure=meta['transport_failure'],meta_path=str(croot/'meta.json'))
  if meta.get('simulated'):record['simulated']=True
  q['calls'].append(record);q['n_calls']+=int(meta['started']);q['raw_tokens_known']+=raw or 0;q['raw_tokens_accounted']+=account;q['n_unknown']+=int(not meta['usage_known']);q['rate_limit_evidence']+=meta['rate_limit_evidence']
  qpath.write_text(json.dumps(q,ensure_ascii=False,indent=2)+'\n')
  budget['n_calls']+=int(meta['started']);budget['raw_tokens_accounted']+=account;budget['t_model_s']+=meta['elapsed_s'];budget['updated_unix']=time.time();bpath.write_text(json.dumps(budget,indent=2)+'\n')
  snapshot=yaml.safe_load((run_dir/'config_snapshot.yaml').read_text()) if (run_dir/'config_snapshot.yaml').exists() else {}
  row=dict(run_id=run_dir.name,method='calibration' if purpose=='calib' else run_dir.parent.parent.name,dut=snapshot.get('dut',''),seed=snapshot.get('seed',''),call_id=call_id,purpose=purpose,target_group=os.environ.get('LLMCMP_TARGET_GROUP',''),t_start=meta['start_utc'],t_end=meta['end_utc'],t_model_s=meta['elapsed_s'],exit_code=meta['exit_code'],status='simulated' if meta.get('simulated') else 'ok' if meta['ok'] else 'failed',model_reported=meta['model_reported'],effort_reported=meta['effort_reported'],cli_version=meta['cli_version'],tok_in=u.get('input_tokens'),tok_in_cached=u.get('cached_input_tokens'),tok_out=u.get('output_tokens'),tok_reasoning=u.get('reasoning_output_tokens'),usage_known=meta['usage_known'],contaminated=meta['contaminated'],n_reconnect=meta['n_reconnect'],schema_ok=meta['schema_ok'])
  from ratchet.llm.ledger import calls
  calls(run_dir,row)
  raw_text=(croot/'last_message.json').read_text() if (croot/'last_message.json').exists() else ''
  result=CallResult(meta['ok'],json.loads(raw_text) if meta['schema_ok'] else None,raw_text,dict(input=u.get('input_tokens'),cached_input=u.get('cached_input_tokens'),output=u.get('output_tokens'),reasoning=u.get('reasoning_output_tokens'),known=meta['usage_known']),meta['contaminated'],meta['elapsed_s'],meta)
  reasons=[]
  if meta['contaminated']:reasons.append('contaminated_call')
  if not meta['usage_known']:reasons.append('usage_unknown')
  if meta.get('quota_or_rate_limit'):reasons.append('quota_or_rate_limit')
  if reasons:
   STOP.write_text(json.dumps(dict(reasons=reasons,run_dir=str(run_dir),call_id=call_id,meta_path=str(croot/'meta.json'),time=time.time()),indent=2)+'\n')
   raise EmergencyStop('User decision required: '+','.join(reasons))
  if q['raw_tokens_accounted']>cfg['global_token_cap']:raise QuotaCapReached('Completed call accounted; global cap crossed, stop')
  if budget['raw_tokens_accounted']>cfg['per_run_token_cap']:raise BudgetExhausted('Completed call accounted; run cap crossed')
  return result
