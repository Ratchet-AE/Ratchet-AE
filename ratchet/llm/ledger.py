"""Append-only locked CSV ledgers for model calls."""
from pathlib import Path
import csv,fcntl,json
CALLS='run_id method dut seed call_id purpose target_group t_start t_end t_model_s exit_code status model_reported effort_reported cli_version tok_in tok_in_cached tok_out tok_reasoning usage_known contaminated n_reconnect schema_ok'.split()
TESTS='run_id test_id source_call_id kind prefix_len seg_len status n_units sim_cycles func_new line_new func_cum line_cum t_compile_s t_sim_s trap_storm'.split()
CKPT='run_id method dut seed call_idx t_wall_s tok_in_cum tok_in_cached_cum tok_out_cum tok_reasoning_cum n_calls n_tests n_valid_tests func_hit func_total line_hit line_total ip_line_hit ip_line_total sim_cycles_cum t_model_cum t_sim_cum t_cf_sim_cum'.split()
def append(path,fields,row):
    extra=set(row)-set(fields)
    if extra:raise ValueError('unknown ledger fields: '+str(sorted(extra)))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+',newline='') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0);header=next(csv.reader(f),None)
        if header and header!=fields:raise ValueError('ledger header mismatch')
        f.seek(0,2);w=csv.DictWriter(f,fieldnames=fields)
        if f.tell()==0:w.writeheader()
        w.writerow(row);f.flush()
def calls(root,row):append(Path(root)/'calls.csv',CALLS,row)
def tests(root,row):
    row=dict(row);result=Path(root)/'tests'/str(row.get('test_id',''))/'result.json'
    row['trap_storm']=bool(json.loads(result.read_text()).get('trap_storm',False)) if result.exists() else bool(row.get('trap_storm',False))
    append(Path(root)/'tests.csv',TESTS,row)
def ckpt(root,row):append(Path(root)/'ckpt.csv',CKPT,row)
