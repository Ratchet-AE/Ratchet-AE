"""Run one validated DSL test in a fresh simulator process."""
from pathlib import Path
import importlib,json,os,subprocess,sys,time,shutil
X=Path(__file__).resolve().parents[1]
if str(X) not in sys.path:sys.path.insert(0,str(X))
from tb.dsl.common import ParseError,CompileError
def run_test(dut,obj,seed,out_dir,timeout_s=180):
    if dut not in ('sd','es','ibex'):raise ValueError('unknown DUT')
    out=Path(out_dir).resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'dsl.json').write_text(obj if isinstance(obj,str) else json.dumps(obj,ensure_ascii=False,indent=2))
    result=dict(status='parse_fail',error='',seed=seed,dut=dut,t_compile_s=0,t_sim_s=0,trap_storm=False)
    start=time.monotonic();context=None
    try:
        module=importlib.import_module('dsl.'+dut);test=module.parse(obj)
        driver=module.to_driver(test,out/'build') if dut=='ibex' else module.to_driver(test)
        result['t_compile_s']=time.monotonic()-start
        (out/'driver.json').write_text(json.dumps(driver,ensure_ascii=False,indent=2))
        result['n_units']=len(test.get('inputs',test.get('ops',[]))) if dut!='ibex' else None
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=f'{X}/selftest:{X}/harness:{X}/duts/sd/tb:{X}',LLMCMP_XB=str(X),LLMCMP_DUT=dut,LLMCMP_OUT=str(out),LLMCMP_DRIVER=str(out/'driver.json'),LLMCMP_SEED=str(seed),RANDOM_SEED=str(seed),LIBPYTHON_LOC=subprocess.check_output([str(Path(sys.executable).parent/'cocotb-config'),'--libpython'],text=True).strip(),PYTHONHOME=sys.prefix,COCOTB_RESULTS_FILE=str(out/'results.xml'),MODULE=os.environ.get('LLMCMP_COCOTB_MODULE','dsl_cocotb'),TOPLEVEL='xb_'+dut,TOPLEVEL_LANG='verilog')
        binary=X/('build/sd/Vtop' if dut=='sd' else 'build/es_model/Vtop' if dut=='es' else 'build/ibex_model/Vibex_simple_system')
        binary=Path(os.environ.get('LLMCMP_SIM_BINARY',str(binary)))
        if dut=='ibex':
            from tb.harness.ibex_status import observed_binary
            binary=observed_binary(binary)
        cpu=min(os.sched_getaffinity(0));cmd=['taskset','-c',str(cpu),str(binary)]
        if os.environ.get('LLMCMP_STOP_CYCLE'):cmd+=['+m1_stop_cycle='+os.environ['LLMCMP_STOP_CYCLE']]
        if dut=='ibex':cmd+=['--raminit='+driver['elf'],'--term-after-cycles=2000000']
        (out/'sim_command.json').write_text(json.dumps(cmd));start=time.monotonic()
        try:
            with (out/'sim.log').open('w') as log:p=subprocess.run(cmd,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout_s)
        finally:result['t_sim_s']=time.monotonic()-start
        if dut=='ibex':
            from tb.harness.ibex_status import summary as ibex_observation
            context=ibex_observation(out)
        if p.returncode and not (context and context['trap_storm']):raise RuntimeError('simulator exit '+str(p.returncode))
        if dut=='ibex':
            log=(out/'sim.log').read_text()
            if 'Terminating simulation by software request.' not in log and not context['trap_storm']:
                result['status']='timeout';raise TimeoutError('Ibex reached cycle bound without tohost termination')
            from tb.ibex.cov.model import model
            e=model(X/'third_party/ibex');samples=list(out.glob('samples_*u_ibex_core*jsonl'))
            if len(samples)!=1:raise RuntimeError('missing/ambiguous main-core samples')
            e.replay_changes(samples[0]);hits={f'{g}.{cp}.{b}':h for g,cp,b,h in e.records()}
            (out/'func_hits.json').write_text(json.dumps(hits,sort_keys=True,separators=(',',':'))+'\n')
            shutil.copyfile(out/'coverage.dat',out/'line.dat');traces=list(out.glob('trace_core*.log'))
            if len(traces)!=1:raise RuntimeError('missing/ambiguous instruction trace')
            shutil.copyfile(traces[0],out/'instruction_trace.log')
            with (out/'trace.jsonl').open('w') as f:
                idx=0
                for line in traces[0].open():
                    cols=line.split()
                    if len(cols)<4 or not cols[0].isdigit():continue
                    f.write(json.dumps(dict(index=idx,cycle=int(cols[1]),pc=cols[2],instruction=cols[3]))+'\n');idx+=1
            result.update(n_units=idx,sim_cycles=int(cols[1]) if cols and len(cols)>1 and cols[1].isdigit() else None)
        else:
            detail=json.loads((out/'sim_result.json').read_text())
            if not detail.get('ok'):raise RuntimeError('cocotb test did not complete')
            result.update(sim_cycles=detail.get('cycles'),observations=detail)
        from tb.harness.union import summary
        result.update(summary(out/'line.dat',out/'func_hits.json',dut));result['status']='trap_storm' if context and context['trap_storm'] else 'ok'
    except ParseError as e:result.update(status='parse_fail',error=str(e))
    except CompileError as e:result.update(status='compile_fail',error=str(e),t_compile_s=time.monotonic()-start)
    except (subprocess.TimeoutExpired,TimeoutError) as e:result.update(status='timeout',error=str(e))
    except Exception as e:result.update(status='sim_fail',error=repr(e))
    if dut=='ibex':
        from tb.harness.ibex_status import summary as ibex_status,timeout_text
        context=context if context is not None else ibex_status(out);result['trap_storm']=context['trap_storm'];result['ibex_observation']=context
        if result['status']=='timeout':
            result['timeout_context']=context;result['error']+=timeout_text(context)
    if result['error']:(out/'error.txt').write_text(result['error'])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--dut',required=True,choices=['sd','es','ibex']);p.add_argument('--test',required=True);p.add_argument('--seed',type=int,default=0);p.add_argument('--out',required=True);a=p.parse_args()
    r=run_test(a.dut,Path(a.test).read_text(),a.seed,a.out);print(json.dumps(r));sys.exit(0 if r['status'] in ('ok','trap_storm') else 1)
