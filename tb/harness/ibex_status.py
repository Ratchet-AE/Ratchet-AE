"""Common, read-only Ibex failure telemetry. No model or ledger calls."""
from pathlib import Path
import collections,fcntl,hashlib,json,os,re,shlex,subprocess
X=Path(__file__).resolve().parents[1]
NM=X/'tools/rv32-gcc/lowrisc-toolchain-gcc-rv32imcb-x86_64-20250710-1/bin/riscv32-unknown-elf-nm'
def observed_binary(original):
 original=Path(original).resolve();bind=X/'harness/ibex_status.sv'
 key=hashlib.sha256(original.read_bytes()+bind.read_bytes()).hexdigest()[:20]
 out=X/'build/ibex_status'/key;out.mkdir(parents=True,exist_ok=True);exe=out/'Vibex_simple_system'
 with (out/'build.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if exe.exists():return exe
  record=(original.parent/'Vibex_simple_system__verFiles.dat').read_text().splitlines();line=next(l[3:-1] for l in record if l.startswith('C "'));args=shlex.split(line);cmd=[str(X/'tools/verilator/bin/verilator')];i=0
  while i<len(args):
   token=args[i];i+=1;cmd.append(token)
   if token in ['-LDFLAGS','-CFLAGS']:
    vals=[]
    while i<len(args):
     a=args[i];allowed=a.startswith(('-Wl,','-L','-l','-pthread')) if token=='-LDFLAGS' else a.startswith(('-std=','-D','-I','-O'))
     if not allowed:break
     vals.append(a);i+=1
    cmd.append(' '.join(vals))
  for flags,value in [(('-Mdir','--Mdir'),str(out)),(('-j','--j'),'4')]:
   flag=next((f for f in flags if f in cmd),None)
   if flag:cmd[cmd.index(flag)+1]=value
   else:cmd.extend([flags[0],value])
  cmd.append(str(bind))
  if '--build' not in cmd:cmd.append('--build')
  (out/'build_command.json').write_text(json.dumps(cmd,indent=2)+'\n')
  env=dict(os.environ);env.pop('VERILATOR_ROOT',None)
  with (out/'build.log').open('w') as log:r=subprocess.run(cmd,cwd=X,env=env,stdout=log,stderr=subprocess.STDOUT)
  if r.returncode or not exe.exists():raise RuntimeError('Ibex telemetry build failed: '+str(out/'build.log'))
 return exe

def summary(out):
 out=Path(out);hist=collections.Counter();priv=None;lastpc=None;end=None;bad=0;storm=False;storm_detail=None
 f=out/'ibex_status.jsonl'
 if f.exists():
  for line in f.open():
   try:e=json.loads(line)
   except ValueError:bad+=1;continue
   if e['event']=='trap_storm':storm=True;storm_detail=e
   if e['event']=='trap':hist[('interrupt:' if e['interrupt'] else 'exception:')+str(e['cause'])]+=1
   if 'privilege' in e:priv=e['privilege']
   if 'last_rvfi_pc' in e:lastpc=e['last_rvfi_pc']
   if e['event']=='final':end=e['cycle']
 traces=list(out.glob('trace_core*.log'))
 if traces:
  with traces[0].open('rb') as t:
   t.seek(max(0,traces[0].stat().st_size-65536));tail=t.read().decode(errors='replace').splitlines()
  for line in reversed(tail):
   a=line.split('\t')
   if len(a)>=6 and line.strip() and re.fullmatch('[0-9a-f]{8}',a[2].strip()):lastpc=int(a[2],16);break
 return dict(trap_storm=storm,storm_detail=storm_detail,last_rvfi_pc=hex(lastpc) if lastpc is not None else 'unknown',privilege={0:'U',1:'S',3:'M'}.get(priv,'unknown'),mcause_top3=hist.most_common(3),trap_total_observed=sum(hist.values()),telemetry_partial_lines=bad,telemetry_final_cycle=end)
def timeout_text(context):
 return '\nIbex timeout context (last persisted observations): last RVFI PC='+context['last_rvfi_pc']+'; current privilege='+context['privilege']+'; mcause histogram top 3='+json.dumps(context['mcause_top3'])
