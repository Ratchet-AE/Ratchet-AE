"""Rebuild the original simulation command with one additional read-only bind.

Never writes RTL or the original build directory. CPU jobs capped at 4.
"""
from pathlib import Path
import shlex,subprocess,json,re,os
from ratchet.slicing.tracker import X
def build(dut,bind_file,out_dir,jobs=2,lint_only=False):
    out=Path(out_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    original=X/('build/sd' if dut=='sd' else 'build/es_model' if dut=='es' else 'build/ibex_model')
    prefix='Vibex_simple_system' if dut=='ibex' else 'Vtop'
    record=(original/f'{prefix}__verFiles.dat').read_text().splitlines()
    cmdline=next(l[3:-1] for l in record if l.startswith('C "'))
    args=shlex.split(cmdline);normalized=[];i=0
    while i<len(args):
        token=args[i];normalized.append(token);i+=1
        if token in ('-LDFLAGS','-CFLAGS'):
            values=[]
            while i<len(args):
                a=args[i]
                allowed=a.startswith(('-Wl,','-L','-l','-pthread')) if token=='-LDFLAGS' else a.startswith(('-std=','-D','-I','-O'))
                if not allowed:break
                values.append(a);i+=1
            normalized.append(' '.join(values))
    cmd=['verilator']+normalized
    # Verilator may have been invoked via an absolute binary in the original env.
    import shutil
    binary=str(X/'tools/verilator/bin/verilator')
    cmd[0]=binary
    for flag,value in [('-Mdir',str(out)),('-j',str(min(jobs,4)))]:
        actual=next((f for f in (flag,'-'+flag) if f in cmd),None)
        if actual:cmd[cmd.index(actual)+1]=value
        else:cmd += [flag,value]
    cmd += [str(Path(bind_file).resolve()),str(X/'harness/ibex_status.sv')]
    if '--build' not in cmd:cmd += ['--build']
    if lint_only:
        cmd=[a for a in cmd if a not in ('--exe','--build') and not a.endswith(('.cpp','.cc','.cxx'))]
        cmd=['--lint-only' if a in ('-cc','--cc') else a for a in cmd]
    (out/'build_command.json').write_text(json.dumps(cmd,indent=2))
    with (out/'build.log').open('w') as log:
        env=dict(os.environ);env.pop('VERILATOR_ROOT',None)
        p=subprocess.run(cmd,cwd=X,env=env,stdout=log,stderr=subprocess.STDOUT)
    if p.returncode:raise RuntimeError(f'monitor compilation failed, see {out}/build.log')
    if lint_only:return Path(bind_file)
    executable=out/prefix
    if not executable.exists():raise RuntimeError('monitor binary missing')
    return executable
