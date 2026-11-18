"""Command entry point."""

def main():
    import argparse,sys
    from pathlib import Path
    from .build import main
    from .io import X
    from ..paths import BASE_COV_DIR, RUNS_DIR
    p=argparse.ArgumentParser();p.add_argument('command',choices=['build']);p.add_argument('--dut',choices=['ibex'],required=True);p.add_argument('--rebuild',action='store_true');p.add_argument('--base-cov',type=Path);p.add_argument('--audit-open-log',type=Path);a=p.parse_args()
    out=RUNS_DIR/a.dut/'m1'
    if a.rebuild and out.exists():
        i=1
        while out.with_name(out.name+f'_backup{i}').exists():i+=1
        out.rename(out.with_name(out.name+f'_backup{i}'))
    sys.exit(main(a.dut, a.base_cov or BASE_COV_DIR(a.dut), a.audit_open_log))

if __name__ == "__main__":
    main()
