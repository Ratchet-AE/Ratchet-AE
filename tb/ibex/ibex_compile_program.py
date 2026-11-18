"""Command entry point."""

def main():
    import os,subprocess,sys,re
    from pathlib import Path
    p=Path(sys.argv[1]);s=p.read_text().replace('tohost: .dword 0;', '.set tohost, 0x20008;')
    s=re.sub(r'\bsb(set|clr|inv|ext)(i?)\b',r'b\1\2',s)
    s=s.replace('mtvec_handler:', '.balign 256\nmtvec_handler:')
    q=p.with_suffix('.adapted.S');q.write_text(s)
    root=Path(os.environ['XBENCH_THIRD_PARTY'])/'riscv-dv'
    cmd=[os.environ['RISCV32_TOOLCHAIN']+'/bin/riscv32-unknown-elf-gcc','-march=rv32imcb','-mabi=ilp32','-nostdlib','-nostartfiles','-static','-mcmodel=medany','-Wl,--no-relax','-T',os.environ['XBENCH_WORKSPACE']+'/duts/ibex/tb/rand.ld','-I'+str(root/'user_extension'),'-o',str(p.with_suffix('.elf')),str(q),os.environ['XBENCH_WORKSPACE']+'/duts/ibex/tb/boot.S']
    subprocess.run(cmd,check=True)

if __name__ == "__main__":
    main()
