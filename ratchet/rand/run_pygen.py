"""Command entry point."""

def main():
    """Seed Python and PyVSC explicitly; execute the pinned generator unchanged."""
    import sys,os,random
    from pathlib import Path
    root=Path(os.environ['XBENCH_THIRD_PARTY'])/'riscv-dv'
    test=sys.argv[1];sys.argv=sys.argv[1:]
    if test=='riscv_rand_instr_test' and '--num_of_sub_program' in sys.argv:
     sys.argv[sys.argv.index('--num_of_sub_program')+1]='5' # Upstream test sets this before randomization.
    seed=sys.argv[sys.argv.index('--seed')+1]
    random.seed(seed)
    sys.path[:0]=[str(root/'pygen'),str(root/'pygen/pygen_src/test')]
    import importlib
    _pkg = importlib.import_module('pygen_src.riscv_instr_pkg')
    globals().update({k: v for k, v in vars(_pkg).items() if not k.startswith('_')})
    from pygen_src.riscv_instr_gen_config import cfg
    from vsc.model.rand_state import RandState
    cfg.set_randstate(RandState.mkFromSeed(seed))
    p=root/'pygen/pygen_src/test'/f'{test}.py'
    exec(compile(p.read_text(),str(p),'exec'),globals())

if __name__ == "__main__":
    main()
