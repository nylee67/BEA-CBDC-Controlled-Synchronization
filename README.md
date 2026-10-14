# BEA-CBDC: Controlled Synchronization Simulation

This repository contains the simulation code accompanying the research manuscript
**A Hierarchical Blockchain Architecture with Controlled Synchronization for CBDC Operation**.

The experiments investigate (i) cutoff-based settlement synchronization over varying numbers of access chains (ACs), and (ii) a two-stage participation-threshold (barrier) alternative.

## Source files (four Python programs)

| File | Purpose |
| --- | --- |
| `bea_cbdc_basic.py` | Reference cutoff-based controlled synchronization simulation engine. |
| `run_bea_cbdc_tables34_30_simple.py` | Baseline/scalability repetition for the manuscript's Tables 3 and 4. |
| `bea_cbdc_basic_barrier_fair.py` | Comparison engine using two-stage, participation-threshold barrier synchronization. |
| `run_bea_cbdc_barrier_30_fair.py` | Barrier experiments for 70%, 80% and 90% participation thresholds. |

## Requirements

Python 3.10+ with NumPy, pandas and Matplotlib:

```bash
python -m pip install -r requirements.txt
```

The full-scale experiments are memory- and CPU-intensive; use a machine with sufficient RAM and disk capacity, and expect runs to take substantial time. Neither precomputed transaction data nor large NPZ outputs are included.

## Reproducing baseline and scalability experiments

```bash
python run_bea_cbdc_tables34_30_simple.py
```

The wrapper runs `N_AC = 1000, 500, 100` with ten pseudorandom seeds, 42–51, for 30 runs total. Default simulation settings are declared in the reference engine, including 100 million user accounts, 1,000 nominal EC rounds and `Delta_R = 1000 ms`. This script intentionally uses the unchanged reference simulation logic and captures in-memory arrays to avoid writing large intermediate NPZ files. It prints progress every 100 EC rounds.

Outputs in `tables34_30runs/`:

- `all_30_runs.csv`: per-seed simulation statistics (written after each completed run).
- `Table3_10runs.csv`: aggregated baseline metrics and 95% Student-t confidence intervals.
- `Table4_10runs.csv`: per-AC-count metrics and 95% Student-t confidence intervals.

**Restart note:** this baseline wrapper does not currently resume from an existing CSV; rerunning from the beginning overwrites results.

## Reproducing the barrier comparison

Quick functional smoke test (small model, *not* a paper result):

```bash
python run_bea_cbdc_barrier_30_fair.py --smoke-test
```

Full experiment:

```bash
python run_bea_cbdc_barrier_30_fair.py
```

The barrier experiment varies the threshold `q` over 70%, 80% and 90%, with ten seeds (42–51) per threshold. Both barrier stages use `ceil(q * eligible_count)` as their respective trigger: stage 1 counts total AC reports; stage 2 counts readiness reports from the ACs admitted in stage 1. There are no fixed cutoffs in these stages. The remaining processing parameters and request generation follow the baseline model. ACs retain their independent local timing.

The barrier simulation uses **the same nominal physical transaction-arrival horizon**, rather than fixing the number of barrier EC rounds. As the barrier creates variable-length rounds, throughput is reported per **1,000 simulated milliseconds**, not just per EC round. The program additionally reports average round duration, latency, backlog and monetary deviation.

Outputs in `barrier_30runs_fair/`:

- `barrier_all_30_runs.csv`: per-seed statistics, written after each completed run.
- `Barrier_Comparison_10runs.csv`: summary by barrier threshold, including 95% confidence intervals (after completion).

The barrier wrapper skips completed threshold/seed pairs from its existing results CSV unless `--reset` is used.

## Evaluation notes

- Fixed cutoff and barrier experiments need to be compared using the same simulated-time observation interval. `Throughput per EC Round` is not directly comparable when EC round durations differ.
- Report success is the share of ACs admitted at stage 1. Readiness success is conditional on stage 1 participation.
- Transaction latency is measured from the recorded request timestamp to its recorded completion timestamp, for completed transactions in the selected observation interval.
- Simulation results are stochastic and depend on seeds, model assumptions and configuration.
- The default simulation is an architectural model, not a production implementation or an end-to-end performance benchmark.

## Outputs, privacy and version control

Large generated arrays, logs and result folders are intentionally excluded through `.gitignore`. No actual user account data or credentials are included; the model generates synthetic users and transactions.

## Citation and usage rights

If using the code in research, cite the associated manuscript. A bibliographic DOI may be added when assigned. A distribution/reuse license has **not yet been selected by the author**; public visibility alone does not grant reuse rights. Add a `LICENSE` file after the author chooses one.