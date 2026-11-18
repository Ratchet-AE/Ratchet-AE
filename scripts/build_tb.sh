#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
  echo 'Usage: bash scripts/build_tb.sh <dut>'
  exit 0
fi
if [[ $# -ne 1 || ! "$1" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo 'Usage: bash scripts/build_tb.sh <dut>' >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$root/tb/$1/build.sh"
