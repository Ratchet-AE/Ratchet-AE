"""Command-line entry point for the existing scheduler."""
import argparse
import runpy
import sys
from .paths import RUNS_DIR
import os


def main():
    parser = argparse.ArgumentParser(description="Run the Ratchet scheduler.")
    parser.add_argument('--config', required=True)
    parser.add_argument('--dut', required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--llm', choices=('api', 'mock'), default='api')
    parser.add_argument('--dry-run', action='store_true', help='stop after a synthetic first response without network or simulation')
    args = parser.parse_args()
    required = ('RATCHET_API_BASE', 'RATCHET_API_KEY', 'RATCHET_MODEL') if args.llm == 'api' else ()
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        parser.error('Missing environment variables: ' + ', '.join(missing))
    from .sched.mock import MockModel
    from .sched.adapters import UnifiedCaller
    output = RUNS_DIR / args.dut / args.config / ('seed' + str(args.seed))
    sys.argv = ['ratchet.sched', 'mock', '--config', args.config, '--seed', str(args.seed), '--out', str(output)]
    if args.dry_run:
        sys.argv.append('--dry-run')
    from .sched.__main__ import main as scheduler_main
    scheduler_main(MockModel() if args.llm == 'mock' else UnifiedCaller(output, dry_run=args.dry_run), dut=args.dut)


if __name__ == '__main__':
    main()
