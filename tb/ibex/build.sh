#!/usr/bin/env bash
set -euo pipefail
RATCHET_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RATCHET_RTL="${RATCHET_RTL:-$RATCHET_REPO/third_party}"
RATCHET_RUNS="${RATCHET_RUNS:-$RATCHET_REPO/runs}"
mkdir -p "$RATCHET_RUNS/ibex/build"
export RATCHET_RTL RATCHET_REPO
envsubst '${RATCHET_RTL} ${RATCHET_REPO}' < "$RATCHET_REPO/tb/ibex/tb/rtl.f.in" > "$RATCHET_RUNS/ibex/build/rtl.f"
exec "${VERILATOR:-verilator}" --cc --exe --build --coverage --top-module ibex_simple_system --Mdir "$RATCHET_RUNS/ibex/build/obj" -f "$RATCHET_RUNS/ibex/build/rtl.f"
