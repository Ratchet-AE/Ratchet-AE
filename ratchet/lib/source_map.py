"""Map executed PCs to original DSL assembly lines without changing instructions.

A separate -g assembly is for metadata only. Assert .text byte equivalence to
the frozen converter's ELF; this debug ELF is never used as evaluated stimulus.
"""
from pathlib import Path
import subprocess,json
from ratchet.slicing.tracker import X
def source_map(out,test):
    out=Path(out);cached=out/'pc_to_primitive.json'
    if cached.exists():return json.loads(cached.read_text())
    build=out/'build';cmd=json.loads((build/'compile_command.json').read_text());original=Path(cmd[cmd.index('-o')+1]);debug=build/'mapping.elf';cmd[cmd.index('-o')+1]=str(debug);cmd.insert(1,'-g')
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode:raise RuntimeError('diagnostic source-map build failed: '+p.stderr)
    prefix=str(Path(cmd[0]).parent/'riscv32-unknown-elf-')
    for elf,name in [(original,'original.text'),(debug,'mapping.text')]:
        subprocess.run([prefix+'objcopy','--only-section=.text','-O','binary',str(elf),str(build/name)],check=True,capture_output=True)
    if (build/'original.text').read_bytes()!=(build/'mapping.text').read_bytes():raise RuntimeError('source mapping would change instruction bytes; refusing')
    pcs=sorted({json.loads(l)['pc'] for l in (out/'trace.jsonl').open()});lines=subprocess.check_output([prefix+'addr2line','-e',str(debug),*['0x'+pc for pc in pcs]],text=True).splitlines()
    start=(X/'dsl/ibex_template/start.S').read_text().split('/* PROGRAM_BODY */')[0].count('\n')+1;length=len(test['asm'].splitlines());mapping={}
    for pc,line in zip(pcs,lines):
        try:n=int(line.rsplit(':',1)[1].split()[0])-start
        except ValueError:continue
        if 0<=n<length:mapping[pc]=n
    cached.write_text(json.dumps(mapping,indent=2)+'\n');return mapping
