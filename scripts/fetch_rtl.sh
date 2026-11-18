#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$root/third_party/ibex"
commit=c0c07085791e4d16a0f2d9a753b2fb79d72e5ffa
if [[ ! -d "$target/.git" ]]; then
  mkdir -p "$(dirname "$target")"
  git clone https://github.com/lowRISC/ibex.git "$target"
fi
git -C "$target" fetch origin "$commit"
git -C "$target" checkout --detach "$commit"
git -C "$target" submodule update --init --recursive
