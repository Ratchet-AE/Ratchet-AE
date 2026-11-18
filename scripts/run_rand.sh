#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
  echo 'Usage: bash scripts/run_rand.sh ibex'
  exit 0
fi
if [[ "${1:-}" != 'ibex' ]]; then
  echo 'Expected DUT: ibex' >&2
  exit 2
fi
exec python -m ratchet.rand.runner
