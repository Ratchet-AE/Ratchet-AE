"""RAND-rdv runner; seed, budget, workers and output are explicit environment settings."""
from pathlib import Path
from ratchet.paths import REPO_ROOT, RTL_DIR, RUNS_DIR
import os,subprocess,time,json,csv,hashlib,random,concurrent.futures,gzip,shutil,re
from tb.harness.covdat import parse_dat,summarize
from tb.ibex.cov.model import model
W=REPO_ROOT;D=REPO_ROOT;R=RTL_DIR/'riscv-dv'
SEED=int(os.environ.get('XBENCH_SEED','0'));WORKERS=int(os.environ.get('XBENCH_WORKERS','4'))
OUT=Path(os.environ.get('XBENCH_RUN_DIR',str(RUNS_DIR/f'ibex/rand/seed{SEED}')));BUDGET=float(os.environ.get('XBENCH_BUDGET_S','600'))

def task(idx,deadline):
 p=OUT/f'programs/p{idx:05d}';p.mkdir(parents=True)
 seed=int.from_bytes(hashlib.sha256(f'{SEED}:{idx}'.encode()).digest()[:4],'big')
 supported=[t.strip() for t in (W/'duts/ibex/rdv_tests.txt').read_text().splitlines() if t.strip() and not t.startswith('#')]
 typ=random.Random(seed).choice(supported)
 result=dict(index=idx,seed=seed,test=typ,success=False,t_gen_s=0,t_compile_s=0,t_sim_s=0,t_merge_s=0,sim_cycles=0)
 env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
 def execute(cmd,phase,cwd):
  result['failed_phase']=phase
  t=time.monotonic()
  try:
   with (p/(phase+'.log')).open('w') as f:
    c=subprocess.run(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=max(1,deadline-time.monotonic()))
   if c.returncode:raise RuntimeError(f'{phase} exited {c.returncode}')
  finally:result['t_'+phase+'_s']=time.monotonic()-t
 try:
  execute(['python',str(W/'scripts/run_pygen.py'),typ,'--target','rv32imcb','--gen_test',typ,'--seed',str(seed),'--num_of_tests','1','--instr_cnt','200','--num_of_sub_program',('5' if typ=='riscv_rand_instr_test' else '0'),'--asm_file_name',str(p/'program'),'--log_file_name',str(p/'pygen.log')],'gen',R)
  execute(['python',str(W/'scripts/ibex_compile_program.py'),str(p/'program_0.S')],'compile',p)
  execute([str(D/'build/ibex_model/Vibex_simple_system'),'--raminit='+str(p/'program_0.elf'),'--term-after-cycles=2000000'],'sim',p)
  txt=(p/'sim.log').read_text();m=re.search(r'Executed cycles:\s*(\d+)',txt);result['sim_cycles']=int(m[1]) if m else 0
  result['success']='Terminating simulation by software request.' in txt and (p/'coverage.dat').exists()
  if not result['success']:result['error']='No software completion / timeout'
 except Exception as e:
  result['error']=str(e)
  result['failure_reason']='budget_cutoff' if isinstance(e,subprocess.TimeoutExpired) and time.monotonic()>=deadline-1 else 'generation_error' if result['failed_phase']=='gen' else 'elf_compile_error' if result['failed_phase']=='compile' else 'simulation_error'
 if result['success']:result['failed_phase']=None;result['failure_reason']=None
 elif 'failure_reason' not in result:
  txt=(p/'sim.log').read_text() if (p/'sim.log').exists() else ''
  result['failure_reason']='cycle_timeout' if 'Simulation timeout' in txt else 'illegal_address' if 'out of range' in txt or 'invalid address' in txt.lower() else 'tohost_not_written'
 return p,result

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if (OUT/'run.log').exists():raise SystemExit('Refuse to overwrite existing run')
 if os.statvfs(D).f_bavail*os.statvfs(D).f_frsize<20*1024**3:raise SystemExit('Insufficient free disk')
 os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:WORKERS])
 start=time.monotonic();deadline=start+BUDGET;e=model(D/'third_party/ibex');count=fail=cycles=0;failure_counts={'n_gen_fail':0,'n_compile_fail':0,'n_sim_fail_only':0,'n_budget_truncated':0};timings={f't_{k}_s':0. for k in ['gen','compile','sim','merge']};idx=0;last=0;ckpt=0
 cols=['run_id','dut','rand_variant','seed','ckpt_idx','t_wall_s','n_units','sim_cycles','n_sim_fail',*failure_counts,'func_hit','func_total','line_hit','line_total','branch_hit','branch_total','toggle_hit','toggle_total',*timings]
 final=OUT/'cov_final.dat';latest={}
 with (OUT/'run.log').open('w',buffering=1) as log,(OUT/'ckpt.csv').open('w',newline='',buffering=1) as cf,(OUT/'program_results.jsonl').open('w',buffering=1) as rf:
  cw=csv.DictWriter(cf,fieldnames=cols);cw.writeheader();log.write(f'RAND-rdv seed{SEED} budget{BUDGET}; {WORKERS} workers; CPUs={sorted(os.sched_getaffinity(0))}; pinned sources\n')
  def checkpoint():
   nonlocal ckpt,latest
   cov=summarize([p for p in parse_dat(final) if '/third_party/ibex/rtl/ibex_' in p['file'] and '.u_ibex_top' in p['fields'].get('h','')]) if final.exists() else {}
   latest=dict(run_id=f'ibex-RAND-rdv-seed{SEED}',dut='ibex',rand_variant='RAND-rdv',seed=SEED,ckpt_idx=ckpt,t_wall_s=time.monotonic()-start,n_units=count,sim_cycles=cycles,n_sim_fail=fail,**failure_counts,**e.summary(),**timings)
   for k,typ in [('line','v_line'),('branch','v_branch'),('toggle','v_toggle')]:
    for stat in ['hit','total']:latest[k+'_'+stat]=cov.get(typ,{}).get(stat,0)
   cw.writerow(latest);cf.flush();ckpt+=1
   if final.exists():shutil.copyfile(final,OUT/f'cov_ckpt_{ckpt:03d}.dat')
  with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
   pending={}
   while time.monotonic()<deadline or pending:
    while time.monotonic()<deadline and len(pending)<WORKERS:
     future=pool.submit(task,idx,deadline);pending[future]=idx;idx+=1
    if not pending:break
    done,_=concurrent.futures.wait(pending,timeout=1,return_when=concurrent.futures.FIRST_COMPLETED)
    for f in done:
     pending.pop(f);p,r=f.result();count+=1;cycles+=r['sim_cycles']
     for key in timings:timings[key]+=r.get(key,0)
     if r['success']:
      t=time.monotonic();cov=p/'coverage.dat'
      if final.exists():
       merged=OUT/'cov_merge.tmp.dat';subprocess.run(['verilator_coverage','--write',str(merged),str(final),str(cov)],stdout=log,stderr=subprocess.STDOUT,check=True);merged.replace(final)
      else:shutil.copyfile(cov,final)
      logs=list(p.glob('samples_*u_ibex_core*jsonl'))
      if len(logs)!=1:raise RuntimeError('Missing primary-core sampling log')
      for group in e.groups.values():
       for point in group.points.values():point.history.clear()
      e.replay_changes(logs[0],n_units=count)
      timings['t_merge_s']+=time.monotonic()-t
      cov.unlink() # Cumulative raw coverage is retained, individual copies are redundant.
     else:
      fail+=1
      key='n_budget_truncated' if r['failure_reason']=='budget_cutoff' else 'n_gen_fail' if r.get('failed_phase')=='gen' else 'n_compile_fail' if r.get('failed_phase')=='compile' else 'n_sim_fail_only'
      failure_counts[key]+=1
     rf.write(json.dumps(r)+'\n');log.write(json.dumps(r)+'\n')
     for raw in [*p.glob('samples_*.jsonl'),*p.glob('trace_core*.log')]:
      with raw.open('rb') as src,gzip.open(str(raw)+'.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
      raw.unlink()
    if time.monotonic()-last-start>=60:checkpoint();last=time.monotonic()-start
   checkpoint()
  e.export(OUT/'func_bins.csv');latest['functional_scope']='uarch_cg subset: 30 points + 11 crosses; primary core; 373 bins'
  latest['failure_rate_pct']=100*fail/count if count else 100
  latest['failure_rate_below_10pct']=latest['failure_rate_pct']<10
  latest['completed_programs']=count-fail;latest['budget_s']=BUDGET
  (OUT/'complete.json').write_text(json.dumps(latest,indent=2)+'\n');print(json.dumps(latest,indent=2))
if __name__=='__main__':main()
