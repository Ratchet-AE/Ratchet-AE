"""Exact-key additive Verilator and functional coverage union, per-DUT scope."""
from pathlib import Path
import json,fnmatch
from tb.harness.covdat import parse_dat
def in_scope(p,dut,ip_only=False):
    f=p['file'];h=p['fields'].get('h','')
    if p['type']!='v_line':return False
    if dut=='sd':return f.endswith('/third_party/ml4dv/stride_detector/stride_detector.sv')
    if dut=='ibex':return '/third_party/ibex/rtl/' in f and fnmatch.fnmatch(Path(f).name,'ibex_*.sv') and Path(f).name not in ('ibex_tracer.sv','ibex_top_tracing.sv') and '.u_ibex_top' in h
    if ip_only:return '/hw/ip/entropy_src/rtl/' in f
    return ('/hw/ip/entropy_src/rtl/' in f or '/hw/ip/tlul/rtl/' in f or '/hw/ip/prim' in f and '/rtl/' in f) and Path(f).name!='tlul_cmd_intg_gen.sv'
def summary(dat,hits,dut):
    points=parse_dat(dat);func=json.loads(Path(hits).read_text())
    line=[p for p in points if in_scope(p,dut)];ip=[p for p in points if in_scope(p,dut,True)] if dut=='es' else []
    return dict(line_hit=sum(p['hits']>0 for p in line),line_total=len(line),func_hit=sum(v>0 for v in func.values()),func_total=len(func),ip_line_hit=sum(p['hits']>0 for p in ip) if dut=='es' else None,ip_line_total=len(ip) if dut=='es' else None)
def merge(test_dirs,out_dir,dut):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);counts={};hits={};keys=None;fkeys=None
    for directory in test_dirs:
        directory=Path(directory)
        result=json.loads((directory/'result.json').read_text())
        if result['status'] not in ('ok','trap_storm'):raise ValueError('only ok tests may enter coverage union')
        points=parse_dat(directory/'line.dat');current={p['key'] for p in points}
        fh=json.loads((directory/'func_hits.json').read_text())
        if keys is not None and (current!=keys or set(fh)!=fkeys):raise ValueError('coverage universe mismatch')
        keys=current;fkeys=set(fh)
        for p in points:counts[p['key']]=counts.get(p['key'],0)+p['hits']
        for k,v in fh.items():hits[k]=hits.get(k,0)+v
    (out/'cov_union.dat').write_text('# SystemC::Coverage-3\n'+''.join(f"C '{k}' {v}\n" for k,v in sorted(counts.items())))
    (out/'func_union.json').write_text(json.dumps(hits,sort_keys=True)+'\n')
    result=summary(out/'cov_union.dat',out/'func_union.json',dut)
    (out/'coverage_summary.json').write_text(json.dumps(result,indent=2)+'\n');return result
