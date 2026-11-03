# BEA-CBDC: Controlled Synchronization Simulation

This repository contains the simulation code accompanying the manuscript
**Controlled Synchronization of Independent Access Chains for CBDC Settlement**
(previous title: *A Hierarchical Blockchain Architecture with Controlled Synchronization for CBDC Operation*).

The experiments investigate (i) cutoff-based settlement synchronization over varying numbers of access chains (ACs), (ii) temporary traffic bursts, AC failures, and synchronization-timing sensitivity, and (iii) a two-stage participation-threshold (barrier) alternative.

## Source files

| File | Purpose |
| --- | --- |
| `bea_cbdc_basic.py` | Reference cutoff-based controlled synchronization simulation engine. It can be executed directly after modifying the `Config` settings and, for the burst flag, the `__main__` block. |
| `run_bea_cbdc_tables34_50_simple.py` | Updated baseline/AC-population experiment for manuscript Tables 3 and 4: five AC counts and ten seeds (50 runs). |
| `run_bea_cbdc_tables34_30_simple.py` | Original three-AC-count, 30-run experiment retained for reproducing the earlier results. |
| `bea_cbdc_basic_barrier_fair.py` | Engine containing the barrier-based simulation function `run_barrier_simulation()`. |
| `run_bea_cbdc_barrier_30_fair.py` | Runs the barrier experiments for 70%, 80% and 90% participation thresholds (Table 8). |
| `run_bea_cbdc_table9_7.py` | Table 9 integrated runner: one time-based cutoff and six barrier configurations under the same destination-fair queue policy and archived failure schedule. |
| `run_bea_cbdc_table9_t0_280_retry.py` | Six-barrier runner used by the integrated Table 9 runner; retained as a dependency. |
| `bea_cbdc_table9_t0_280_retry_barrier.py` | Table 9 recovery-aware, two-stage barrier simulation engine. |
| `bea_cbdc_table9_t0_280_retry_core.py` | Table 9 common simulation and destination-fair transaction-queue primitives. |
| `table9_t0_280_retry_analysis.py` | Analysis functions imported by the Table 9 runner (invoke the runner, not this helper directly). |
| `Table9_T0_280_Retry_Failure_Schedule_Input.csv` | Archived failure schedule used by the full Table 9 experiment. |
| `run_bea_cbdc_table10_t0_280_retry.py` | Table 10 runner: cutoff plus six barrier configurations; original/extreme failure scenarios. |
| `bea_cbdc_table10_t0_280_retry_cutoff.py` | Table 10 cutoff engine with the shared destination-fair queue policy. |
| `bea_cbdc_table10_t0_280_retry_barrier.py` | Table 10 recovery-aware barrier engine with/without timeout. |
| `table10_t0_280_retry_analysis.py` | Analysis functions imported by the Table 10 runner (invoke the runner, not this helper directly). |

**Reproduction principle.** Tables 5, 6, and 7 use the *same* cutoff-based source file, `bea_cbdc_basic.py`, with only the indicated experiment parameters changed. No separate HalfAC, HalfEC, or temporary-failure implementation is required. Use the stated settings before each run and restore the baseline settings afterward. The updated 50-run wrapper is used for Tables 3 and 4; the original 30-run wrapper remains available for the earlier three-configuration results. The separate barrier wrapper reproduces Table 8. The integrated Table 9 runner evaluates one cutoff and six barrier configurations under the same archived AC failure schedule and destination-fair queue policy. It does not use the original FIFO-based Table 6 result as its cutoff comparison row. The Table 10 runner separately evaluates the same seven synchronization configurations under a more severe failure schedule. The original Table 6 experiment retains its FIFO policy; it is a separate experiment, not a row in the controlled Table 9 comparison.

## Requirements

Python 3.10+ with NumPy, pandas and Matplotlib:

```bash
python -m pip install -r requirements.txt
```

On systems where `python` is not Python 3, replace it in the commands below with `python3`.

Full-scale experiments are memory- and CPU-intensive. Use a machine with sufficient RAM and disk capacity. Neither precomputed transaction data nor large NPZ outputs are included in the repository.

## Reproducing baseline and scalability experiments (Tables 3 and 4)

**Current experiment (five AC configurations, 50 runs):**

```bash
python run_bea_cbdc_tables34_50_simple.py
```

The wrapper runs `N_AC = 1000, 500, 100, 50, 25` with ten independent pseudorandom seeds (42-51) for each configuration, giving **50 runs in total**. It uses the unchanged cutoff-based engine, `bea_cbdc_basic.py`, located in the same directory. Default settings include a **fixed population of 100 million simulated user accounts**, 1,000 EC rounds of 1,000 ms each, a system-wide arrival rate of 100 transfer requests/ms, and a nominal limit of 4,000 transactions per AC local synchronization round. For every run, the wrapper disables burst traffic (`Flag_Burst = False`) and temporary AC failures (`P_Fail_AC = 0`).

The experiment varies the **number of access chains**, not the number of user accounts. Holding total traffic fixed while decreasing the number of ACs increases the average incoming load assigned to each AC:

| `N_AC` | Mean requests per AC per 1,000 ms | Ratio to the nominal 4,000-transaction local-round capacity |
| ---: | ---: | ---: |
| 1000 | 100 | 2.5% |
| 500 | 200 | 5% |
| 100 | 1,000 | 25% |
| 50 | 2,000 | 50% |
| 25 | 4,000 | 100% |

**Interpretation:** these are average arrival loads over 1,000 ms and nominal capacity ratios, not guarantees of completed transactions per EC round. ACs maintain independent local rounds and may carry unsettled transactions across EC rounds. The added 50- and 25-AC configurations are intended to examine behavior as per-AC demand approaches the configured local processing capacity.

The wrapper collects run statistics in memory without saving large intermediate NPZ files and prints progress every 100 EC rounds. The baseline summary (Table 3) continues to use **`N_AC = 1000`**. Table 4 includes all five AC configurations and reports averages and 95% Student-t confidence intervals across the ten seeds for each configuration.

Outputs in `tables34_50runs/`:

- `all_50_runs.csv`: per-seed statistics, updated after each completed run.
- `Table3_10runs.csv`: 1,000-AC baseline metrics with 95% confidence intervals.
- `Table4_10runs.csv`: five-configuration comparison of backlog per AC, total backlog, transaction latency, and pending CBDC, each with 95% confidence intervals.

**Original experiment (three AC configurations, 30 runs):** the prior wrapper is retained for reproducing the earlier results:

```bash
python run_bea_cbdc_tables34_30_simple.py
```

It runs `N_AC = 1000, 500, 100` with the same ten seeds and writes `all_30_runs.csv`, `Table3_10runs.csv`, and `Table4_10runs.csv` to `tables34_30runs/`.

**Restart note:** neither wrapper resumes from an existing results CSV. Restarting a wrapper starts from the first configuration/seed and overwrites its own output files. The two wrappers use separate output directories and do not overwrite each other's results.

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

## Reproducing synchronization comparisons under temporary AC failures (Table 9)

Table 9 evaluates **seven single-run configurations**: one time-based cutoff, three barriers without timeouts (`q = 0.7, 0.8, 0.9`), and three barriers with timeouts at the same thresholds. All seven use the **same destination-fair transaction-selection policy**, the same archived AC failure schedule, and the same synthetic workload settings. This allows Table 9 to compare the synchronization mechanisms without also changing their queue policy.

**Queue policy.** The original Table 6 cutoff simulation uses first-in, first-out (FIFO) transaction selection: requests are selected in arrival order. Destination-fair scheduling preserves FIFO order *within* each destination AC and selects across destination ACs by round robin. It was introduced to mitigate the potential concentration of transaction selection on a small number of destinations during AC unavailability; it does not predict failures or imply proven performance superiority over FIFO. Table 9 reruns the cutoff with destination-fair scheduling instead of reusing the FIFO-based Table 6 cutoff values. Table 6 remains unchanged.

**Required files** (all in the repository root):

- `run_bea_cbdc_table9_7.py` (public entry point for the seven configurations)
- `run_bea_cbdc_table9_t0_280_retry.py` (six-barrier runner invoked by the entry point)
- `bea_cbdc_table9_t0_280_retry_barrier.py`
- `bea_cbdc_table9_t0_280_retry_core.py`
- `table9_t0_280_retry_analysis.py`
- `run_bea_cbdc_table10_t0_280_retry.py` (cutoff execution and summary helpers)
- `bea_cbdc_table10_t0_280_retry_cutoff.py` (destination-fair cutoff engine)
- `Table9_T0_280_Retry_Failure_Schedule_Input.csv` (required archived failure schedule)

Full-size settings: `N_AC = 1000`, `N_User = 100_000_000`, `N_Round = 1000`, `Delta_R = 1000` ms, `lambda_tx = 100.0` requests/ms, no burst traffic, and seed 42. The archived CSV identifies exactly 500 ACs, each with one temporary failure beginning in reference seconds 100-800 and lasting 20-100 seconds. Failures follow a **fixed physical-time schedule** shared by all mechanisms, even though barrier EC rounds have variable duration. Do not replace the input CSV with a newly generated failure schedule.

### Table 9 barrier rules

The first-stage quorum is `ceil(q * N_AC)`. The second-stage readiness quorum is `ceil(q * N_T0)`, where `N_T0` is the number of ACs admitted at T0 in that EC round. No-timeout barriers wait for the requisite reports, including after temporary AC recovery. Timed barriers close each reporting stage when either the quorum is reached or its timeout expires:

| Threshold | T0 timeout, relative to round opening | T2 timeout, relative to T1 |
| ---: | ---: | ---: |
| `q = 0.7` | 280 ms | 443 ms |
| `q = 0.8` | 280 ms | 510 ms |
| `q = 0.9` | 280 ms | 616 ms |

After a prepared T0 report misses the stage deadline, its AC may restart only after receiving the preliminary matrix announcement at `t2` (T1 plus communication delay). The cutoff retains its predefined EC reporting and readiness boundaries.

### Run Table 9

List all seven configurations without running them:

```bash
python -u run_bea_cbdc_table9_7.py --list
```

**Reproduce all seven Table 9 configurations in one command** (recommended for readers):

```bash
python -u run_bea_cbdc_table9_7.py --mode all
```

This first invokes the original six-barrier runner (which skips previously recorded configurations), then runs the destination-fair cutoff (which also skips an existing matching result). A fresh checkout without saved results computes **all seven** sequentially. For an independent full recomputation where saved outputs already exist, use `--reset-barriers --rerun-cutoff` together with `--mode all`.

To run **only** the new cutoff experiment without rerunning the six barriers:

```bash
python -u run_bea_cbdc_table9_7.py --mode cutoff
```

Optional reduced-size functional test (not a paper result):

```bash
python -u run_bea_cbdc_table9_7.py --mode all --smoke-test
```

**Important:** the current integrated runner defaults to `--mode cutoff` if `--mode` is omitted. Readers reproducing the entire table should explicitly use `--mode all`. The wrapper also supports `--mode barrier`, `--mode timeout --q 0.9`, `--progress-every N`, and `--barrier-summary PATH` for an existing six-barrier result file.

**Outputs.** The merged seven-row summary is `table9_t0_280_retry_7runs/Table9_T0_280_Retry_All_7.csv`. The same folder contains `Table9_T0_280_Retry_Cutoff.csv`, `Table9_T0_280_Retry_Cutoff_Metadata.json`, `Table9_T0_280_Retry_Cutoff_Rounds.csv`, and a cutoff console log. The six-barrier runner writes its summary as `table9_t0_280_retry_barrier_6runs/Table9_T0_280_Retry_Barrier_All_6.csv`. Reduced-size test output folders use the `_smoke` suffix. These results are **single simulation runs**, not averages across seeds or confidence-interval estimates.

## Reproducing severe AC failure comparisons (Table 10)

Table 10 runs **seven single-run configurations** under the same failure schedule and transaction-generation settings within a given scenario: one time-based cutoff, three no-timeout barriers, and three barriers with timeouts. The cutoff and all barriers use the **same destination-fair transaction-queue policy**, allowing an internally consistent Table 10 comparison.

**Required files** (all in the repository root):

- `run_bea_cbdc_table10_t0_280_retry.py`
- `bea_cbdc_table10_t0_280_retry_cutoff.py`
- `bea_cbdc_table10_t0_280_retry_barrier.py`
- `table10_t0_280_retry_analysis.py`

Full-size settings: `N_AC = 1000`, `N_User = 100_000_000`, `N_Round = 1000`, `Delta_R = 1000` ms, `lambda_tx = 100.0` requests/ms, 500 ACs selected to fail once, no burst traffic, and seed 42. The Table 10 runner generates its failure schedule deterministically; **no input failure CSV is required**.

Two failure scenarios are supported:

| `--scenario` | Failure start (reference seconds) | Failure duration (seconds) |
| --- | ---: | ---: |
| `extreme` (default) | 100-300 | 300-600 |
| `original` | 100-500 | 100-400 |

Under `extreme`, all 500 selected ACs are unavailable concurrently during reference seconds 300-399. No-timeout barriers continue waiting for recovery and eventual quorum rather than applying an undisclosed timeout. An uncompleted stage at the 1,000,000-ms observation horizon is recorded with an appropriate noncompleted status, not treated as a completed settlement round.

The T0 quorum is `ceil(q * N_AC)`; the T2 readiness quorum is `ceil(q * N_T0)`. The timed barriers use **(T0, T2) = (280, 443), (280, 510), (280, 616) ms** for `q = 0.7, 0.8, 0.9`, respectively. Prepared T0 reports that miss the deadline are retried after T1 announcement reception at `t2`, not merely when T1 occurs. All Table 10 modes use the same queue discipline.

### Run Table 10

List planned runs:

```bash
python -u run_bea_cbdc_table10_t0_280_retry.py --scenario extreme --list
```

Run all seven variants in the extreme scenario (full experiment):

```bash
python -u run_bea_cbdc_table10_t0_280_retry.py --scenario extreme
```

Run only time-based cutoff and timed barrier `q = 0.9` (two-run comparison):

```bash
python -u run_bea_cbdc_table10_t0_280_retry.py --scenario extreme --pair
```

Run just the six barrier variants, or select one configuration:

```bash
python -u run_bea_cbdc_table10_t0_280_retry.py --scenario extreme --barriers-only
python -u run_bea_cbdc_table10_t0_280_retry.py --scenario extreme --mode timeout --q 0.9
```

Optional reduced-size functional test (not a paper result):

```bash
python -u run_bea_cbdc_table10_t0_280_retry.py --scenario extreme --smoke-test
```

Use `--scenario original` for the alternate long-failure scenario. `--reset`, `--progress-every N`, and `--audit-retries` are also supported. The `--pair` option cannot be combined with `--mode`, `--q`, or `--barriers-only`. Already recorded completed/terminal-status runs are skipped unless `--reset` is supplied.

**Outputs:** `table10_t0_280_retry_extreme/` (or `table10_t0_280_retry_original/`; smoke variants append `_smoke`). The main summary is `Table10_T0_280_Retry_All_7.csv`, even if only a subset of configurations was run. Additional outputs include `Table10_T0_280_Retry_Scenario.json`, the failure schedule and concurrent-failure CSVs, `Table10_T0_280_Retry_Cutoff_Rounds.csv`, per-barrier round CSVs and the cutoff console log.

Interpret completed-request mean latency together with unfinished requests, backlog, throughput, barrier waiting time, and incomplete-stage status. These simulations demonstrate a specified scenario rather than a statistically averaged or production-system performance guarantee.

## Evaluation and reproducibility notes

- For Tables 5, 6, and 7, `bea_cbdc_basic.py` writes the **same hard-coded NPZ filename** each time. Preserve or rename results before the next run.
- Manual changes to the `Config` dataclass are the intended way to reproduce the single-run variants without maintaining multiple source-code copies. Change only the documented parameters for each variant.
- Standard statistical analysis in the paper excludes rounds 0-9 and 990-999 of a 1,000-round experiment. For a 2,000-round timing variant, check the corresponding observation window in physical time and the analysis being reproduced; do not accidentally compare unequal observation horizons.
- Cutoff and barrier results must use comparable simulated-time horizons. `Throughput per EC Round` cannot be directly compared if EC round durations vary.
- Transaction latency is measured from request timestamp to completion timestamp for transactions **requested within** the selected observation window and eventually completed, even when completion occurs after that window. Uncompleted transactions must not be silently counted as zero-latency completions.
- The 100 million simulated user accounts are held fixed in the AC-population experiments; these experiments do **not** measure scalability as the number of user accounts changes.
- Simulation results are stochastic and depend on random seeds and model assumptions. They are architectural-model results, not production CBDC performance benchmarks.

## Outputs, privacy, and version control

Large generated arrays (`*.npz`, `*.npy`) and the legacy output directories are excluded through `.gitignore`. The Table 9 runners write into `table9_t0_280_retry_7runs*/` and `table9_t0_280_retry_barrier_6runs*/`; the Table 10 runner writes into `table10_t0_280_retry_*/`. These generated directories are excluded by `.gitignore`; do not commit generated results or logs. Do not commit generated result CSVs, logs or other large outputs. The checked-in `Table9_T0_280_Retry_Failure_Schedule_Input.csv` is an intentional, required small input file, not a generated result. No actual user account data or credentials are included; the model generates synthetic users and transactions.

## Citation and usage rights

If using the code in research, cite the associated manuscript. A bibliographic DOI may be added when assigned. A distribution/reuse license has **not yet been selected by the author**; public visibility alone does not grant reuse rights. Add a `LICENSE` file after choosing one.
