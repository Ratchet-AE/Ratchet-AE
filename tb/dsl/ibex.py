from pathlib import Path
import subprocess,tempfile
from .common import X,parse_obj,check_schema,ParseError,CompileError
GCC=X/'tools/rv32-gcc/lowrisc-toolchain-gcc-rv32imcb-x86_64-20250710-1/bin/riscv32-unknown-elf-gcc'
TEMPLATE=X/'dsl/ibex_template'
def check(test):
    errors=check_schema(test,'ibex')
    if errors:return errors
    if not test['asm'].strip(): errors.append('asm: empty program body')
    # A program body cannot open host files or replace the fixed sections.
    import re
    if re.search(r'^\s*\.(include|incbin|section|pushsection|popsection|previous|org)\b',test['asm'],re.M):errors.append('asm: file/section directives are reserved for the fixed template')
    if re.search(r'^\s*(?:_start|_xb_\w+)\s*:',test['asm'],re.M):errors.append('asm: reserved template label')
    return errors
def parse(obj):
    test=parse_obj(obj,'ibex');errors=check(test)
    if errors:raise ParseError('\n'.join(errors))
    return test
def to_driver(test,out_dir=None):
    test=parse(test);out=Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix='ibex-driver-'));out.mkdir(parents=True,exist_ok=True)
    source=(TEMPLATE/'start.S').read_text().replace('/* PROGRAM_BODY */',test['asm'])
    (out/'program.S').write_text(source)
    cmd=[str(GCC),'-march=rv32imcb','-mabi=ilp32','-nostdlib','-nostartfiles','-Wl,--no-relax','-T',str(TEMPLATE/'link.ld'),str(out/'program.S'),'-o',str(out/'program.elf')]
    (out/'compile_command.json').write_text(__import__('json').dumps(cmd))
    try:p=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
    except (OSError,subprocess.TimeoutExpired) as e:
        (out/'compile.log').write_text(str(e));raise CompileError(str(e)) from e
    (out/'compile.log').write_text(p.stdout+p.stderr)
    if p.returncode:raise CompileError(p.stdout+p.stderr)
    return {'elf':str((out/'program.elf').resolve()),'asm':test['asm']}
