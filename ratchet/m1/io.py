"""Static build inputs and compiled line metadata (keys only, never hits)."""
from pathlib import Path
import json,hashlib,csv,os
from ..paths import REPO_ROOT
X=REPO_ROOT

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_json(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def write_csv(p,rr,fields):
    with Path(p).open('w',newline='') as f:
        w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rr)
def rows(p):
    with Path(p).open() as f:return list(csv.DictReader(f))
def config(dut):
    if dut!='hpdcache':
        p=X/f'analysis_funnel/config/{dut}.yaml';c=json.loads(p.read_text())
        if dut=='ibex':
            assert len(c['param_overrides'])==14
            c['extra_top_modules']=['xb_ibex_bind']  # Same observer bind source, retained for static sampling-expression binding.
            for filename,h in next(v for k,v in c.items() if k.endswith('_filelists')).items():assert sha(filename)==h,filename
        return c
    root=X/'case_hpdcache';src=[];incs=[];visited=set()
    def filelist(p):
        p=Path(p)
        if p in visited:return
        visited.add(p)
        for line in p.read_text().splitlines():
            line=line.strip().replace('${HPDCACHE_DIR}',str(root/'hpdcache_src'))
            if not line or line.startswith(('#','//')):continue
            if line.startswith('-F '):filelist(line[3:].strip())
            elif line.startswith('+incdir+'):incs.extend(line.split('+')[2:])
            elif line.endswith(('.sv','.v')):src.append(line)
    filelist(root/'tb/official_case.Flist')
    # Exclude the bound logger; include exactly the actual case top.
    assert any(p.endswith('hpdcache_case_top.sv') for p in src)
    return dict(dut=dut,src_list=src,include_dirs=incs,defines=['VERILATOR=1'],top='hpdcache_case_top',dut_root='hpdcache_case_top.i_hpdcache',dut_module='hpdcache',exclude=[],seed_base='hpdcache_case_top.i_hpdcache',param_overrides=[])

def split_args(text,start):
    args=[];level=0;quoted=False;escape=False;last=start
    for i in range(start,len(text)):
        ch=text[i]
        if quoted:
            if escape:escape=False
            elif ch=='\\':escape=True
            elif ch=='"':quoted=False
            continue
        if ch=='"':quoted=True
        elif ch=='(':level+=1
        elif ch==')':
            if level==0:args.append(text[last:i].strip());return args,i+1
            level-=1
        elif ch==',' and level==0:args.append(text[last:i].strip());last=i+1
    return [],len(text)

def line_points(dut):
    folder=X/('case_hpdcache/tb/obj' if dut=='hpdcache' else f'build/{dut}_model');points={};source=[]
    for p in sorted(folder.glob('*Slow.cpp')):
        txt=p.read_text();pos=0;used=False
        while True:
            pos=txt.find('__vlCoverInsert(',pos)
            if pos<0:break
            aa,pos=split_args(txt,pos+len('__vlCoverInsert('))
            if len(aa)<10 or aa[1]!='first':continue
            try:f=json.loads(aa[3]);line=int(aa[4]);col=int(aa[5]);h,page,comment,lc=map(json.loads,aa[6:10])
            except (ValueError,TypeError):continue
            if not page.startswith('v_line/'):continue
            scope=('/third_party/ibex/rtl/' in f and Path(f).name.startswith('ibex_') and Path(f).name not in ('ibex_tracer.sv','ibex_top_tracing.sv') and '.u_ibex_top' in h) if dut=='ibex' else (('/hw/ip/entropy_src/rtl/' in f or '/hw/ip/tlul/rtl/' in f or '/hw/ip/prim' in f and '/rtl/' in f) and Path(f).name!='tlul_cmd_intg_gen.sv') if dut=='es' else '/hpdcache_src/rtl/src/' in f
            if not scope:continue
            item=dict(file=str(Path(f).resolve()),line=line,col=col,page=page,comment=comment,linescov=lc)
            key=json.dumps(item,sort_keys=True);points.setdefault(key,dict(item,cov_point=dut+':'+hashlib.sha256(key.encode()).hexdigest()[:20]));used=True
        if used:source.append(dict(path=str(p),sha256=sha(p)))
    if dut=='ibex':assert len(points)==1105,('line universe mismatch',len(points))
    assert points,('no compiled line metadata',dut)
    return list(points.values()),source

def target_bins(dut, base_cov):
    if dut=='hpdcache':
        # Source-only target declarations, not attempt results.
        p=X/'case_hpdcache/targets/targets.json'
        if not p.exists():
            matches=list((X/'case_hpdcache/targets').glob('*.json'))
            p=next(v for v in matches if 'targets' in json.loads(v.read_text()))
        data=json.loads(p.read_text())
        return [dict(bin_id=t['id'],group_id=t['id'],covergroup='hpdcache',target=t) for t in data['targets']]
    base={};meta={}
    for seed in range(3):
        for r in rows(Path(base_cov)/f'seed{seed}'/'func_bins.csv'):
            base[r['bin_id']]=base.get(r['bin_id'],0)+int(r['hits']);meta[r['bin_id']]=r
    excluded=set()
    if dut=='ibex':
        p=X/'tb/ibex/unreachable_bins.tsv'
        with p.open() as f:excluded={r['bin_id'] for r in csv.DictReader(f,delimiter='\t')}
    else:
        # The target list is static and pre-existing; RAND still determines misses.
        allowed={r['target_id'] for r in rows(X/'analysis_funnel/data/target_list.csv') if r['dut']=='es'}
        excluded=set(base)-allowed
    result=[dict(bin_id=k,group_id=meta[k]['covergroup']+'.'+meta[k]['coverpoint_or_cross'],covergroup=meta[k]['covergroup'],point=meta[k]['coverpoint_or_cross'],bin_name=meta[k]['bin_name']) for k in base if not base[k] and k not in excluded]
    if dut=='ibex':assert len(result)==202
    return result
