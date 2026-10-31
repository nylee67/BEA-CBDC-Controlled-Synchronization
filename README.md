# BEA-CBDC: Controlled Synchronization Simulation

This repository contains the simulation code accompanying the manuscript
**Controlled Synchronization of Independent Access Chains for CBDC Settlement**
(previous title: *A Hierarchical Blockchain Architecture with Controlled Synchronization for CBDC Operation*).

The experiments investigate (i) cutoff-based settlement synchronization over varying numbers of access chains (ACs), (ii) temporary traffic bursts, AC failures, and synchronization-timing sensitivity, and (iii) a two-stage participation-threshold (barrier) alternative.

## Source files

| File | Purpose |
| --- | --- |
| `bea_cbdc_basic.py` | Reference cutoff-based controlled synchronization simulation engine. It can be executed directly after modifying the `Config` settings and, for the burst flag, the `__main__` block. |
| `run_bea_cbdc_tables34_30_simple.py` | Baseline/scalability repetition for manuscript Tables 3 and 4. |
| `bea_cbdc_basic_barrier_fair.py` | Engine containing the barrier-based simulation function `run_barrier_simulation()`. |
| `run_bea_cbdc_barrier_30_fair.py` | Runs the barrier experiments for 70%, 80% and 90% participation thresholds (Table 8). |

**Reproduction principle.** Tables 5, 6, and 7 use the *same* cutoff-based source file, `bea_cbdc_basic.py`, with only the indicated experiment parameters changed. No separate HalfAC, HalfEC, or temporary-failure implementation is required. Use the stated settings before each run and restore the baseline settings afterward. The two existing wrappers are retained for the repeated-run results of Tables 3, 4, and 8.

## Requirements

Python 3.10+ with NumPy, pandas and Matplotlib:

```bash
python -m pip install -r requirements.txt
```

On systems where `python` is not Python 3, replace it in the commands below with `python3`.

Full-scale experiments are memory- and CPU-intensive. Use a machine with sufficient RAM and disk capacity. Neither precomputed transaction data nor large NPZ outputs are included in the repository.

## Reproducing baseline and scalability experiments (Tables 3 and 4)

```bash
python run_bea_cbdc_tables34_30_simple.py
```

The wrapper runs `N_AC = 1000, 500, 100` with ten pseudorandom seeds, 42-51, for 30 runs total. Default simulation settings are declared in the reference engine, including 100 million user accounts, 1,000 nominal EC rounds, and `Delta_R = 1000 ms`. The wrapper sets `Flag_Burst = False` and `P_Fail_AC = 0` for each run. It captures arrays in memory to avoid writing large intermediate NPZ files and prints progress every 100 EC rounds.

Outputs in `tables34_30runs/`:

- `all_30_runs.csv`: per-seed statistics, written after each completed run.
- `Table3_10runs.csv`: aggregated baseline metrics and 95% Student-t confidence intervals.
- `Table4_10runs.csv`: per-AC-count metrics and 95% Student-t confidence intervals.

**Restart note:** this baseline wrapper does not resume from an existing CSV; restarting it overwrites the results.

## Reproducing the burst-traffic experiment (Table 5)

**Source:** `bea_cbdc_basic.py`. This is a single-run scenario, not a ten-seed confidence-interval experiment.

In the `Config` class, use the following values (the corresponding variable names are present in the released source file):

| Parameter | Value | Interpretation |
| --- | --- | --- |
| `N_AC` | `1000` | Number of ACs |
| `N_Round` | `1000` | Number of EC rounds |
| `Delta_R` | `1000` | EC round duration, ms |
| `N_Tx_per_AC_block` | `4000` | Maximum transactions per AC local round |
| `lambda_tx` | `100.0` | Normal requests/ms |
| `lambda_tx_burst` | `2000.0` | Burst requests/ms |
| `R_burst` | `500` | First burst round |
| `L_burst` | `50` | Burst length (rounds 500-549) |
| `P_Fail_AC` | `0.0` | No temporary AC failures |
| `seed` | `42` | Random seed |

**Important:** in the released source, the `__main__` block assigns `cfg.Flag_Burst = False` *after* constructing `Config`. For Table 5, change that line in the `__main__` block to:

```python
cfg.Flag_Burst = True
```

Then run:

```bash
python bea_cbdc_basic.py
cp Result_AC1000_NTX4000.npz Result_AC1000_NTX4000_Table5.npz
```

The command produces the simulator's regular log/console results and `Result_AC1000_NTX4000.npz`. The second command preserves the Table 5 output under a unique name, because the reference simulator otherwise reuses the same NPZ filename for every experiment.

For the Table 5 analysis, use the simulated request round (request timestamp divided by `Delta_R`) to separate the pre-burst interval from rounds 500-549. Compute request-to-completion latency from the request and completion timestamps for completed transactions. The output arrays `backlog` and `Sum_pending_balance` provide system-wide backlog and pending CBDC over EC rounds; the peak and recovery behavior can be evaluated from their round-by-round series. Exclude the initialization/end-boundary rounds when applying the paper's reported evaluation window (rounds 10-989).

After this run, restore `cfg.Flag_Burst = False` for the non-burst experiments.

## Reproducing temporary AC failures (Table 6 and Section 5.4)

**Source:** `bea_cbdc_basic.py`. This is a single-run scenario.

Set the following values in the `Config` class:

| Parameter | Value | Interpretation |
| --- | --- | --- |
| `N_AC` | `1000` | Total ACs |
| `N_Round` | `1000` | EC rounds |
| `Delta_R` | `1000` | EC round duration, ms |
| `lambda_tx` | `100.0` | Baseline requests/ms |
| `P_Fail_AC` | `0.5` | Selects 50% of ACs for one temporary failure each |
| `R_Fail_Start` | `100` | Earliest failure starting round |
| `R_Fail_End` | `800` | Latest failure starting round |
| `Min_Fail_Duration` | `20` | Minimum failure duration in rounds |
| `Max_Fail_Duration` | `100` | Maximum failure duration in rounds |
| `seed` | `42` | Random seed |

In the `__main__` block, keep the burst flag disabled:

```python
cfg.Flag_Burst = False
```

Run and preserve the output:

```bash
python bea_cbdc_basic.py
cp Result_AC1000_NTX4000.npz Result_AC1000_NTX4000_Table6_Failure.npz
```

The file contains the exact generated `failure_schedule`, the per-round AC availability array (`num_non_failed_ACs`), transaction timestamps (`Total_Tx`), backlog, and pending CBDC. The failure selection is *not* a per-round Bernoulli draw: 50% of ACs are selected once, and each selected AC is assigned its own randomly chosen failure-start round and duration. Consequently, 50% selected for failure does **not** mean 50% are unavailable simultaneously.

For Table 6, classify completed transactions into (a) all transactions, (b) those whose **sending and receiving ACs both belong to the never-failed set**, and (c) those involving at least one failure-selected AC. Determine group membership from the AC IDs in `failure_schedule`, not solely from whether an endpoint happens to be offline at a transaction's request time. Report mean, standard deviation, P95, and P99 request-to-completion latency for the paper's measurement interval. The time series in the same NPZ file also support the plots and the per-AC recovery analysis in Section 5.4.

After this run, restore `P_Fail_AC = 0.0`.

## Reproducing timing sensitivity (Table 7, Section 6.1)

**Source:** `bea_cbdc_basic.py`. Run each of the four configurations with the *same reference engine*; do not create alternative simulator files. All four configurations disable bursts and AC failures, use `N_AC = 1000`, `lambda_tx = 100.0`, and use `seed = 42`. Keep `cfg.Flag_Burst = False` in `__main__` and `P_Fail_AC = 0.0` in `Config`.

### Timing configurations

| Setting | Baseline | HalfEC | HalfAC | HalfAC+HalfEC |
| --- | ---: | ---: | ---: | ---: |
| `N_Round` | 1000 | 2000 | 1000 | 2000 |
| `Delta_R` (ms) | 1000 | 500 | 1000 | 500 |
| `D_matrix` (ms) | 40 | 20 | 40 | 20 |
| `D_ready` (ms) | 360 | 180 | 360 | 180 |
| `D_participant` (ms) | 280 | 140 | 280 | 140 |
| `D_finalize` (ms) | 40 | 20 | 40 | 20 |
| `D_chaining` (ms) | 280 | 140 | 280 | 140 |
| `d_row` (ms) | 40 | 40 | 20 | 20 |
| `d_check` (ms) | 60 | 60 | 30 | 30 |
| `d_finalize` (ms) | 40 | 40 | 20 | 20 |
| `d_chaining` (ms) | 20 | 20 | 10 | 10 |
| `d_note_max` (ms) | 200 | 200 | 100 | 100 |
| `d_delay_min` (ms) | 20 | 20 | 10 | 10 |
| `d_delay_lambda` (1/ms) | `1/80.0` | `1/80.0` | `1/40.0` | `1/40.0` |

Here, the `D_*` parameters are EC-side coordination intervals and sum to `Delta_R`. The `d_*` parameters are AC-side processing and communication parameters. Halving the exponential mean delay from 80 to 40 ms requires **doubling** its *rate*, i.e., changing `d_delay_lambda` from `1/80.0` to `1/40.0`; dividing that rate by two would increase rather than decrease delays. The initial local phase offsets `epsilon_min = 10` and `epsilon_max = 50` are held fixed in this description; they are not processing or communication delays.

**Equal simulation-time horizon:** HalfEC and HalfAC+HalfEC use `N_Round = 2000` with `Delta_R = 500`, whereas Baseline and HalfAC use `N_Round = 1000` with `Delta_R = 1000`. In each case the nominal simulated-time horizon is 1,000,000 ms.

For **each** configuration above, update the corresponding `Config` values in `bea_cbdc_basic.py` and execute:

```bash
python bea_cbdc_basic.py
```

Immediately preserve the resulting file, before running the next configuration:

```bash
# After the baseline run
cp Result_AC1000_NTX4000.npz Result_AC1000_NTX4000_Baseline.npz

# After the HalfEC run
cp Result_AC1000_NTX4000.npz Result_AC1000_NTX4000_HalfEC.npz

# After the HalfAC run
cp Result_AC1000_NTX4000.npz Result_AC1000_NTX4000_HalfAC.npz

# After the HalfAC+HalfEC run
cp Result_AC1000_NTX4000.npz Result_AC1000_NTX4000_HalfAC_HalfEC.npz
```

Each NPZ contains the simulation configuration (`cfg`), completed transaction timestamps (`Total_Tx`), backlog, reporting and readiness success arrays, and monetary-state arrays. To reproduce the columns in Table 7, compute mean request-to-completion latency (`L`), mean system-wide transaction backlog (`Bsys`), mean settlement-report success (`PR`), and mean readiness success conditional on report success (`PRD`), using the paper's measurement window. Read each saved configuration from the `cfg` object rather than assuming that every NPZ has the same `Delta_R` or `N_Round`.

**Configuration audit.** These instructions express the paper's stated HalfAC/HalfEC timing changes using the variable names in the current source. Before treating the values as a bit-for-bit reproduction of the originally reported Table 7, compare the embedded `cfg` in the original Table 7 NPZ output files (if retained) against the values above, especially the AC-side delay parameters. The released source does not itself include the historical HalfAC/HalfEC overrides.

To inspect the configuration stored in any output file, run (replace the filename as needed):

```bash
python - <<'PY'
import numpy as np
with np.load('Result_AC1000_NTX4000_HalfEC.npz', allow_pickle=True) as data:
    cfg = data['cfg'].item()
    for key in ('N_Round', 'Delta_R', 'D_matrix', 'D_ready',
                'D_participant', 'D_finalize', 'D_chaining',
                'd_row', 'd_check', 'd_finalize', 'd_chaining',
                'd_note_max', 'd_delay_min', 'd_delay_lambda'):
        print(f'{key}: {cfg[key]}')
PY
```

## Reproducing the barrier comparison (Table 8)

Quick functional smoke test (small model, *not* a paper result):

```bash
python run_bea_cbdc_barrier_30_fair.py --smoke-test
```

Full experiment:

```bash
python run_bea_cbdc_barrier_30_fair.py
```

The wrapper varies the threshold `q` over 70%, 80%, and 90%, with ten seeds (42-51) per threshold. Both barrier stages use `ceil(q * eligible_count)` as their respective trigger: stage 1 counts total AC reports, and stage 2 counts readiness reports from the ACs admitted in stage 1. There are no fixed cutoffs or timeouts in these stages. The remaining processing parameters and request generation follow the baseline model, and ACs retain their independent local timing.

**Implementation note:** direct execution of `bea_cbdc_basic_barrier_fair.py` uses its inherited `__main__` block, which invokes `run_simulation()`. To reproduce the barrier results, use the wrapper command above: it explicitly invokes `run_barrier_simulation()`.

The barrier simulation uses the same nominal physical transaction-arrival horizon, rather than fixing the number of barrier EC rounds. As the barrier creates variable-length rounds, throughput is reported per 1,000 simulated milliseconds, not just per EC round. The program also reports average round duration, latency, backlog, and monetary deviation.

Outputs in `barrier_30runs_fair/`:

- `barrier_all_30_runs.csv`: per-seed statistics, written after each completed run.
- `Barrier_Comparison_10runs.csv`: summary by barrier threshold, including 95% confidence intervals.

The barrier wrapper skips completed threshold/seed pairs from its existing results CSV unless `--reset` is used.

## Evaluation and reproducibility notes

- For Tables 5, 6, and 7, `bea_cbdc_basic.py` writes the **same hard-coded NPZ filename** each time. Preserve or rename results before the next run.
- Manual changes to the `Config` dataclass are the intended way to reproduce the single-run variants without maintaining multiple source-code copies. Change only the documented parameters for each variant.
- Standard statistical analysis in the paper excludes rounds 0-9 and 990-999 of a 1,000-round experiment. For a 2,000-round timing variant, check the corresponding observation window in physical time and the analysis being reproduced; do not accidentally compare unequal observation horizons.
- Cutoff and barrier results must use comparable simulated-time horizons. `Throughput per EC Round` cannot be directly compared if EC round durations vary.
- Transaction latency is measured from request timestamp to completion timestamp for transactions **requested within** the selected observation window and eventually completed, even when completion occurs after that window. Uncompleted transactions must not be silently counted as zero-latency completions.
- Simulation results are stochastic and depend on random seeds and model assumptions. They are architectural-model results, not production CBDC performance benchmarks.

## Outputs, privacy, and version control

Large generated arrays, logs, and result folders are excluded through `.gitignore`. No actual user account data or credentials are included; the model generates synthetic users and transactions.

## Citation and usage rights

If using the code in research, cite the associated manuscript. A bibliographic DOI may be added when assigned. A distribution/reuse license has **not yet been selected by the author**; public visibility alone does not grant reuse rights. Add a `LICENSE` file after choosing one.
