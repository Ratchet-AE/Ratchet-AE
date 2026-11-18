"""Resolve repository, runtime, RTL, DUT and baseline coverage locations."""
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get('RATCHET_RUNS', REPO_ROOT / 'runs')).expanduser().resolve()
RTL_DIR = Path(os.environ.get('RATCHET_RTL', REPO_ROOT / 'third_party')).expanduser().resolve()


def DUT_DIR(dut):
    return REPO_ROOT / 'tb' / dut


def BASE_COV_DIR(dut):
    return RUNS_DIR / dut / 'rand'
