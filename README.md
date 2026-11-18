# Ratchet

Ratchet is a coverage-directed verification workflow. It combines static analysis, diagnostic reconciliation and generation scheduling around a hardware testbench.

## Dependencies

The environment file pins Python and the Python libraries used by the original environment. The hardware workflow also needs Verilator, a RISC-V compiler toolchain, Git, and the generator dependencies used by the random regression.

## Installation

Create and activate the environment with `conda env create -f environment.yml` and `conda activate ratchet`. Set `RATCHET_API_BASE`, `RATCHET_API_KEY`, and `RATCHET_MODEL` for API calls. `RATCHET_RUNS` and `RATCHET_RTL` override the runtime and RTL directories.

## Workflow

Run these steps in order:

```sh
bash scripts/fetch_rtl.sh
bash scripts/build_tb.sh ibex
bash scripts/run_rand.sh ibex
python -m ratchet.m1 build --dut ibex
python -m ratchet.run --config r3_cohort --dut ibex --seed 0 --llm api
```

Use `--llm mock` to select the synthetic model. The `--dry-run` option runs the scheduler through the first model response using a synthetic response, records the request and accounting under the run directory, and stops before simulation or network access. It requires the M1 inputs under the runtime directory. A native simulation requires `RATCHET_SIM_BINARY` to point to the simulator executable.

## Layout

`ratchet/` contains the analysis, diagnosis, regeneration, scheduling and model interface. `tb/` contains the simulation harness and DUT assets. `scripts/` contains workflow entry points. Run outputs are stored under `runs/` by default.

## Adding a DUT

Start with `tb/_template/`, add the DUT configuration and adapter under `tb/<dut>/`, and provide its testbench and coverage assets.
