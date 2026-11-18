"""Command entry point."""

def main():
    import argparse,json
    from pathlib import Path
    from . import diagnose
    from ..sched.artifacts import Bundle
    p=argparse.ArgumentParser();p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--trace',type=Path,required=True);p.add_argument('--bin',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    b=Bundle(a.artifacts);rows=[json.loads(l) for l in a.trace.read_text().splitlines()]
    for r in rows:r['state']={k:int(v,16) if isinstance(v,str) else v for k,v in r.get('state',{}).items()}
    result=diagnose(rows,b.specs[a.bin],b.cards,b.conditions);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')

if __name__ == "__main__":
    main()
