"""Generate one read-only change-only bind observer per DUT from elaborated paths."""
from pathlib import Path
import json,pyslang as slang
def generate(tracker,registers,dut,out_dir):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    comp=slang.ast.Compilation();comp.addSyntaxTree(tracker.tree);root=comp.getRoot()
    topname={'sd':'xb_sd','es':'xb_es','ibex':'ibex_simple_system'}[dut]
    top=next((x for x in root.topInstances if x.name==topname),None)
    if top is None:raise ValueError('monitor top not elaborated: '+topname)
    wanted={(r[0],r[1].split('[')[0]) for r in registers};signals=[];unsupported=[]
    def add(path,typ,key):
        if typ.isIntegral:
            signals.append(dict(path=path,register=list(key),width=typ.bitWidth));return
        if typ.isUnpackedArray and typ.hasFixedRange:
            a,b=typ.fixedRange.lower,typ.fixedRange.upper
            for i in range(a,b+1):add(path+f'[{i}]',typ.elementType,(key[0],key[1]+f'[{i}]'))
        else:unsupported.append(dict(path=path,type=str(typ)))
    def visit(symbol):
        if str(symbol.kind)!='SymbolKind.Variable' or symbol.declaringDefinition is None or symbol.parentScope.isUninstantiated or symbol.parentScope.isProceduralContext:return
        key=(symbol.declaringDefinition.name,symbol.name)
        if key in wanted:add(symbol.hierarchicalPath,symbol.type,key)
    top.visit(visit)
    text=[f'module llmcmp_m1_{dut}(input logic clk, input logic rst_n);','integer fd; longint unsigned cycle = 0; longint unsigned stop_cycle = 0;','initial begin fd = $fopen("m1_changes.jsonl", "w"); if ($value$plusargs("m1_stop_cycle=%d", stop_cycle)) begin end end']
    for i,s in enumerate(signals):text += [f'logic [{s["width"]-1}:0] old_{i};',f'bit valid_{i} = 0;']
    text += ['always @(posedge clk) begin','  cycle <= cycle + 1;','  if (rst_n) begin']
    for i,s in enumerate(signals):
        ref='$root.'+s['path'];key='.'.join(s['register']);path=s['path']
        text += [f'    if (!valid_{i} || old_{i} !== {ref}) begin',f'      $fdisplay(fd, "{{\\"cycle\\":%0d,\\"register\\":\\"{key}\\",\\"path\\":\\"{path}\\",\\"value\\":\\"%h\\"}}", cycle, {ref});',f'      old_{i} <= {ref}; valid_{i} <= 1;','    end']
    clock,reset=('clk_sys','rst_sys_n') if dut=='ibex' else ('clk_i','rst_ni')
    text += ['  end','  if (stop_cycle > 0 && cycle >= stop_cycle) $finish;','end','final $fclose(fd);','endmodule',f'bind {topname} llmcmp_m1_{dut} llmcmp_m1_observer(.clk({clock}),.rst_n({reset}));']
    path=out/f'{dut}_bind.sv';path.write_text('\n'.join(text)+'\n')
    from .constants import enum_values
    manifest=dict(dut=dut,top=topname,signals=signals,unsupported=unsupported,registers_requested=[list(x) for x in sorted(wanted)],no_driven_dut_signals=True,clock=clock,reset=reset,enum_values=enum_values(tracker))
    (out/f'{dut}_signals.json').write_text(json.dumps(manifest,indent=2)+'\n');return manifest
