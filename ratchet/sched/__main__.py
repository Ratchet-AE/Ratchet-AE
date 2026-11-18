"""Command entry point."""

def main(caller=None, dut=None):
    """No implicit model launch. Only explicit mock execution in the upgrade CLI."""
    from pathlib import Path
    import argparse,json
    from . import Bundle,Budget,Scheduler,configuration
    from .mock import MockModel,MockExecutor
    from ..paths import RUNS_DIR
    from ..dut_api import load_dut
    p=argparse.ArgumentParser();p.add_argument('--dut');p.add_argument('command',choices=['mock']);p.add_argument('--config',choices=['r3_l0','r3_single','r3_cohort','r3_cohort_v2d'],default='r3_cohort');p.add_argument('--out',type=Path,required=True);p.add_argument('--max-calls',type=int,default=10);p.add_argument('--seed',type=int,default=0);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    dut=dut or a.dut
    if not dut:p.error('--dut is required')
    _,adapter=load_dut(dut)
    bundle=Bundle(RUNS_DIR/dut/'m1');model=caller or MockModel();scheduler=Scheduler(bundle,a.config,a.seed,budget=Budget(1000000,14400,1000000),enable_model_calls=not model.is_mock,dut_adapter=adapter);executor=None if a.dry_run else MockExecutor(bundle) if model.is_mock else __import__('ratchet.sched.adapters',fromlist=['NativeExecutor']).NativeExecutor(a.out, __import__('os').environ['RATCHET_SIM_BINARY'], bundle, seed=a.seed)
    for _ in range(a.max_calls):
        result=scheduler.step(model,executor,stop_after_response=a.dry_run)
        if result.get('stopped'):break
    if a.dry_run:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out/'dry_run.json').write_text(json.dumps(result, indent=2)+'\n')
        if model.is_mock and result.get('stopped') == 'dry_run':
            from ..llm.ledger import calls
            response=result['response']; output=response.get('output_tokens',0)
            row=dict(run_id=a.out.name,method=a.config,dut=dut,seed=a.seed,call_id='call00000',purpose='gen',status='simulated',model_reported='mock',tok_in=response.get('tokens',0)-output,tok_out=output,usage_known=True,contaminated=False,schema_ok=True)
            calls(a.out,row)
            (a.out/'request.json').write_text(json.dumps(dict(text=result['request']['text'],schema=result['schema']),indent=2)+'\n')
        print(json.dumps(dict(config=a.config,stopped=result.get('stopped'),reservation=result.get('reservation'),ledger=str(a.out/'calls.csv'),actual_model_calls=0)))
        return
    scheduler.write(a.out);result=dict(config=a.config,model_calls=getattr(model,'calls',getattr(model,'index',0)),tests=executor.calls)
    print(json.dumps(result))

if __name__ == "__main__":
    main()
