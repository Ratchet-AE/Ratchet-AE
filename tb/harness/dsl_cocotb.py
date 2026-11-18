"""Fixture drivers only; never included in any evaluated method."""
import os,json,random,time
from pathlib import Path
import cocotb
from cocotb.triggers import Timer,ClockCycles,ReadWrite
from cocotb.clock import Clock
from ratchet.paths import REPO_ROOT, RUNS_DIR
X=Path(os.environ.get('LLMCMP_XB', str(REPO_ROOT)));OUT=Path(os.environ.get('LLMCMP_OUT', str(RUNS_DIR)));SEED=int(os.environ.get('LLMCMP_SEED','0'))
def dump_hits(e):return {f'{g}.{p}.{b}':h for g,p,b,h in e.records()}
async def sd(d):
 from sd_monitor import CoverageMonitor
 from global_shared_types import GlobalCoverageDatabase
 fixture=json.loads(Path(os.environ['LLMCMP_DRIVER']).read_text());d.valid_i.value=0;d.value_i.value=0;d.cov_dump_req.value=0;d.rst_ni.value=1
 cocotb.start_soon(Clock(d.clk_i,10,units='ns').start());await Timer(15,units='ns');d.rst_ni.value=0;await ClockCycles(d.clk_i,3);await Timer(5,units='ns');d.rst_ni.value=1;await ClockCycles(d.clk_i,1);await ReadWrite()
 m=CoverageMonitor(d)
 with (OUT/'trace.jsonl').open('w') as f:
  for idx,val in enumerate(fixture['inputs']):
   d.valid_i.value=1;d.value_i.value=val;await ClockCycles(d.clk_i,1);await ReadWrite();m.sample_coverage()
   f.write(json.dumps(dict(index=idx,cycle=idx+6,input=val,stride1=int(d.stride_1_o.value),stride2=int(d.stride_2_o.value),valid1=int(d.stride_1_valid_o.value),valid2=int(d.stride_2_valid_o.value)),separators=(',',':'))+'\n')
 d.cov_dump_req.value=0;await Timer(1,units='ps');d.cov_dump_req.value=1;await Timer(1,units='ps');d.cov_dump_req.value=0;Path('cov_live.dat').replace(OUT/'line.dat')
 (OUT/'func_hits.json').write_text(json.dumps(GlobalCoverageDatabase(m.coverage_database).get_coverage_plan(),sort_keys=True,separators=(',',':'))+'\n');(OUT/'sim_result.json').write_text(json.dumps(dict(ok=True,seed=SEED,cycles=len(fixture['inputs'])+6))+'\n')
async def es(d):
 from common.tlul.host import Host
 from common.tlul.regmap import RegisterMap
 from duts.es.cov.sampler import Sampler
 from duts.es.cov.model import sampled_subset_model
 ot=X/'third_party/opentitan';regmap=RegisterMap(ot,'entropy_src');e=sampled_subset_model(ot,regmap);rng=random.Random(SEED)
 fixture=json.loads(Path(os.environ['LLMCMP_DRIVER']).read_text());trace=(OUT/'trace.jsonl').open('w');events=(OUT/'samples.jsonl').open('w');sampler=Sampler(events,time.time(),regmap)
 primitive_index=-1;feeding=False;saw_ack=False;ack_rises=0;old_ack=0;left_idle=False;idle_state=None
 d.rng_valid.value=0;d.rng_bits.value=0;d.hw_req.value=0;d.xht_response.value=0
 def sideband():
  d.rng_valid.value=int(feeding);d.rng_bits.value=rng.getrandbits(4);d.xht_response.value=0;d.hw_req.value=int(feeding and not saw_ack)
 host=Host(d,rng,sideband,{'main_sm_state':lambda:int(d.main_sm_state.value),'regwen':lambda:int(d.u_dut.u_reg.regwen_qs.value)})
 handles={'module_enable':'module_enable_qs','fips_enable':'conf_fips_enable_qs','fips_flag':'conf_fips_flag_qs','rng_fips':'conf_rng_fips_qs','threshold_scope':'conf_threshold_scope_qs','rng_bit_enable':'conf_rng_bit_enable_qs','rng_bit_sel':'conf_rng_bit_sel_qs','es_route':'entropy_control_es_route_qs','es_type':'entropy_control_es_type_qs','esfinal_fifo_clear_while_disabled':'entropy_control_esfinal_fifo_clear_while_disabled_qs','entropy_data_reg_enable':'conf_entropy_data_reg_enable_qs','fw_ov_mode':'fw_ov_control_fw_ov_mode_qs','entropy_insert':'fw_ov_control_fw_ov_entropy_insert_qs'}
 def monitor(pre):
  nonlocal saw_ack,ack_rises,old_ack,left_idle
  rst=int(d.rst_ni.value);req=int(d.hw_req.value);ack=int(d.hw_ack.value);mod=int(d.u_dut.u_reg.module_enable_qs.value);sm=int(d.main_sm_state.value)
  if rst:
   if ack and not old_ack:ack_rises+=1
   if req and ack:saw_ack=True
   if idle_state is not None and mod==6 and sm!=idle_state:left_idle=True
   old_ack=ack
  trace.write(json.dumps(dict(cycle=host.cycles,rst=rst,rng_valid=int(d.rng_valid.value),rng_bits=int(d.rng_bits.value),req=req,ack=ack,module_enable=mod,sm=sm),separators=(',',':'))+'\n')
  en=d.u_dut.u_entropy_src_core.u_enable_delay;args={}
  if sampler.enable_qq!=sampler.enable_q:
   args={n:int(getattr(en,n).value) for n in ['esrng_fifo_not_empty_i','esbit_fifo_not_empty_i','postht_fifo_not_empty_i','distr_fifo_not_empty_i','sha3_block_busy_i','sha3_block_processed_i','bypass_mode_i','enable_o']}
  config={n:int(getattr(d.u_dut.u_reg,h).value) for n,h in handles.items()} if req and ack else {}
  sampler.interface_cycle(bool(rst),bool(req),bool(ack),int(en.enable_i.value),args,config)
 host.cycle_monitor=monitor;await host.reset();idle_state=int(d.main_sm_state.value)
 primitives=(OUT/'primitives.jsonl').open('w')
 for idx,op in enumerate(fixture['ops']):
  primitives.write(json.dumps(dict(index=idx,cycle=host.cycles,event='begin',op=op['op']))+'\n')
  sampler.units=idx+1
  if op['op']=='wr':
   pre=await host.transaction(True,op['addr'],op['data'],lambda p,o=op:sampler.address(True,o['addr'],o['data'],p),lambda p,o=op:sampler.response(True,o['addr'],p['d_data'],p));assert not pre['d_error'],'TL error in legal selftest write'
  elif op['op']=='wait':
   feeding=True
   for _ in range(op['n']):await host.tick()
  elif op['op'] in ('rd','poll'):
   attempts=op.get('timeout',1);matched=False
   for attempt in range(attempts):
    pre=await host.transaction(False,op['addr'],0,lambda p,o=op:sampler.address(False,o['addr'],0,p),lambda p,o=op:sampler.response(False,o['addr'],p['d_data'],p))
    if pre['d_error']:raise RuntimeError('TL error in read')
    if op['op']=='rd' or (pre['d_data'] & op['mask'])==op['val']:
     matched=True;break
   if not matched:primitives.write(json.dumps(dict(index=idx,cycle=host.cycles,event='poll_timeout',attempts=attempts))+'\n')
  primitives.write(json.dumps(dict(index=idx,cycle=host.cycles,event='end'))+'\n')
 primitives.close()
 module_enable=int(d.u_dut.u_reg.module_enable_qs.value);await host.dump();Path('cov_live.dat').replace(OUT/'line.dat');trace.close();events.close()
 # Replay only this fixture's samples; unsupported groups deliberately excluded by existing subset.
 for line in (OUT/'samples.jsonl').open():
  ev=json.loads(line)
  if ev['covergroup'] in e.groups:e.sample(ev['covergroup'],ev['args'])
 (OUT/'func_hits.json').write_text(json.dumps(dump_hits(e),sort_keys=True,separators=(',',':'))+'\n')
 result=dict(ok=True,seed=SEED,module_enable=module_enable,idle_state=idle_state,left_idle=left_idle,entropy_ack_rises=ack_rises,entropy_ack_seen=saw_ack,cycles=host.cycles)
 (OUT/'sim_result.json').write_text(json.dumps(result,sort_keys=True)+'\n')
 assert result['ok'],'STOP: ES legal-enable selftest has no ack or did not leave Idle'
@cocotb.test()
async def selftest(d):
 if os.environ['LLMCMP_DUT']=='sd':await sd(d)
 else:await es(d)
