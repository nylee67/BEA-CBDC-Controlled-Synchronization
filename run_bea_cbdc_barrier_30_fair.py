#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Barrier-based EC synchronization: 70%, 80%, 90% x 10 seeds.

Requirements: numpy, pandas, matplotlib (used by the original engine).
Place this script in the same folder as bea_cbdc_basic_barrier_fair.py.
Run with the `python` of the bea_sim conda environment:

    python run_bea_cbdc_barrier_30_fair.py

Optional very small execution test:
    python run_bea_cbdc_barrier_30_fair.py --smoke-test

Barrier stage 1: wait until ceil(threshold*N_AC) AC reports arrive.
Barrier stage 2: wait until ceil(threshold*N_report) readiness reports arrive.
Both stages have NO fixed reporting cutoff or timeout. A threshold that
cannot be met because too many ACs are offline causes an explicit error.

Because barrier EC round durations are variable, the simulator stops after
the same nominal physical time horizon (N_Round * Delta_R) rather than
forcing all variants to run an equal number of EC rounds. Completed
transactions per 1000 ms is therefore the meaningful throughput comparison
with the fixed-1000-ms baseline. Raw throughput per EC round is also saved
separately for transparency.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import argparse
import gc
import math
import random
import sys

import numpy as np
import pandas as pd


ENGINE_FILE = Path(__file__).with_name('bea_cbdc_basic_barrier_fair.py')
THRESHOLDS = (0.70, 0.80, 0.90)
SEEDS = range(42, 52)
N_AC = 1000
T_CRITICAL_95_DF9 = 2.262157162740992


METRICS = (
    'Throughput (tx/1000ms)',
    'Latency Mean (ms)',
    'Latency SD (ms)',
    'Latency P95 (ms)',
    'Latency P99 (ms)',
    'Backlog/AC Mean',
    'Total Backlog Mean',
    'Pending Mean',
    'Report Mean',
    'Readiness Mean',
    'EC Round Duration Mean (ms)',
    'Report Barrier Wait Mean (ms)',
    'Readiness Barrier Wait Mean (ms)',
    'Throughput per EC Round',
    'Number of EC Rounds',
    'Max Monetary Deviation',
)


def load_engine():
    if not ENGINE_FILE.is_file():
        raise FileNotFoundError(f'Missing simulator: {ENGINE_FILE}')
    spec = spec_from_file_location('bea_cbdc_barrier_engine', ENGINE_FILE)
    engine = module_from_spec(spec)
    sys.modules[spec.name] = engine  # dataclasses needs a registered module
    spec.loader.exec_module(engine)
    return engine


def simulate(engine, threshold, seed, *, smoke_test=False):
    cfg = engine.Config()
    cfg.N_AC = N_AC
    cfg.seed = seed
    cfg.barrier_threshold = threshold
    cfg.Flag_Burst = False
    cfg.P_Fail_AC = 0.0
    cfg.log_level = 0

    if smoke_test:
        cfg.N_AC = 10
        cfg.N_User = 1_000
        cfg.N_Round = 40
        cfg.lambda_tx = 0.25
        cfg.N_Tx_per_AC_block = 400

    random.seed(seed)
    np.random.seed(seed)
    requests = engine.initialize_request_schedule(cfg)
    transactions = np.empty((int(requests.sum()), 5), dtype=np.int32)
    ids_per_ac = [np.empty(0, dtype=np.int32) for _ in range(cfg.N_AC)]
    engine.generate_Total_Tx(cfg, requests, transactions)
    engine.classify_Total_Tx_per_AC(cfg, transactions, ids_per_ac)

    matrix = np.full((cfg.N_AC, cfg.N_AC), -1, dtype=np.int64)
    return engine.run_barrier_simulation(
        cfg, transactions, ids_per_ac, matrix, progress_every=100
    )


def weighted_average(values, weights):
    if not np.any(weights > 0):
        return float('nan')
    return float(np.average(values, weights=weights))


def analyze(data):
    cfg = data['cfg']
    tx = data['Total_Tx']
    rounds = pd.DataFrame(data['round_metrics'])
    if rounds.empty:
        raise RuntimeError('No completed barrier EC rounds.')

    # Match the reference evaluation interval in physical simulation time.
    eval_start = 10 * cfg['Delta_R']
    eval_end = (cfg['N_Round'] - 10) * cfg['Delta_R']
    if eval_end <= eval_start:
        raise ValueError('N_Round must exceed 20.')

    requested = tx[:, 3]
    completed = tx[:, 4]
    valid_requests = (requested >= eval_start) & (requested < eval_end)
    # Do not credit completions after the fixed observation horizon, even
    # if the final barrier round finishes slightly beyond that horizon.
    finished_in_eval = (valid_requests & (completed >= 0)
                        & (completed < data['Traffic_Horizon_ms']))
    latencies = (
        completed[finished_in_eval].astype(np.int64)
        - requested[finished_in_eval].astype(np.int64)
    )
    if not latencies.size:
        raise RuntimeError('No completed requests in evaluation window.')

    # Throughput is based on simulated wall-clock completion timestamps.
    # One unit is 1000 simulated milliseconds, matching Table 3's 1-s round.
    completions_during_eval = ((completed >= eval_start) & (completed < eval_end))
    eval_duration_ms = eval_end - eval_start
    normalized_throughput = (
        int(np.count_nonzero(completions_during_eval))
        * cfg['Delta_R'] / eval_duration_ms
    )

    # A time-weighted mean avoids giving short and long barrier rounds
    # artificially equal importance when comparing against fixed periods.
    starts = rounds['Round_Open_ms'].to_numpy(dtype=np.int64)
    ends = rounds['Next_Round_Open_ms'].to_numpy(dtype=np.int64)
    weights = np.maximum(0, np.minimum(ends, eval_end)
                         - np.maximum(starts, eval_start)).astype(np.float64)
    relevant = weights > 0
    if not np.any(relevant):
        raise RuntimeError('Barrier rounds did not cover the evaluation interval.')

    total = rounds['Total_CBDC'].to_numpy(dtype=np.int64)
    # int64 is large enough for this model's aggregate CBDC amount.
    monetary_deviation = int(np.max(np.abs(total - total[0])))

    result = {
        'Threshold': cfg['barrier_threshold'],
        'Seed': cfg['seed'],
        'N_AC': cfg['N_AC'],
        'N_User': cfg['N_User'],
        'N_Round_Nominal': cfg['N_Round'],
        'Traffic Horizon (ms)': data['Traffic_Horizon_ms'],
        'Simulation End (ms)': data['Simulation_End_ms'],
        'Number of EC Rounds': data['N_EC_Rounds'],
        'Throughput (tx/1000ms)': normalized_throughput,
        'Throughput per EC Round': float(np.mean(rounds.loc[relevant, 'Completed_Tx'])),
        'Latency Mean (ms)': float(np.mean(latencies)),
        'Latency SD (ms)': float(np.std(latencies)),
        'Latency P95 (ms)': float(np.percentile(latencies, 95)),
        'Latency P99 (ms)': float(np.percentile(latencies, 99)),
        'Completed Requests': int(latencies.size),
        'Requested Transactions': int(np.count_nonzero(valid_requests)),
        'Backlog/AC Mean': weighted_average(rounds['Backlog_per_Active_AC'], weights),
        'Total Backlog Mean': weighted_average(rounds['Total_Backlog'], weights),
        'Pending Mean': weighted_average(rounds['Pending_CBDC'], weights),
        'Report Mean': float(np.mean(rounds.loc[relevant, 'Report_Success'])),
        'Readiness Mean': float(np.mean(
            rounds.loc[relevant, 'Readiness_Success_Given_Report']
        )),
        'EC Round Duration Mean (ms)': float(np.mean(
            rounds.loc[relevant, 'Round_Duration_ms']
        )),
        'Report Barrier Wait Mean (ms)': float(np.mean(
            rounds.loc[relevant, 'Report_Wait_ms']
        )),
        'Readiness Barrier Wait Mean (ms)': float(np.mean(
            rounds.loc[relevant, 'Readiness_Wait_ms']
        )),
        'Initial Total CBDC': int(total[0]),
        'Max Monetary Deviation': monetary_deviation,
    }
    if monetary_deviation != 0:
        raise AssertionError(
            f'Monetary invariant broken in threshold={cfg["barrier_threshold"]}, '
            f'seed={cfg["seed"]}: deviation={monetary_deviation}'
        )
    return result


def mean_and_ci(values):
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    mean = float(np.mean(values))
    if n < 2:
        return mean, float('nan'), float('nan')
    # The planned experiment always has 10 seeds; fail explicitly otherwise.
    if n != 10:
        raise ValueError(f'Expected 10 independent seeds, got {n}.')
    half_width = T_CRITICAL_95_DF9 * float(values.std(ddof=1)) / math.sqrt(n)
    return mean, mean - half_width, mean + half_width


def save_summary(rows, output_dir, *, partial=False):
    df = pd.DataFrame(rows).sort_values(['Threshold', 'Seed'])
    df.to_csv(output_dir / 'barrier_all_30_runs.csv', index=False)
    if partial:
        return

    summary = []
    for threshold in THRESHOLDS:
        subset = df[df['Threshold'].round(2) == threshold]
        if len(subset) != 10:
            raise ValueError(f'Barrier {threshold:.0%} has {len(subset)} runs, needs 10.')
        result = {'Threshold': threshold, 'Runs': len(subset)}
        for key in METRICS:
            mean, lower, upper = mean_and_ci(subset[key])
            result[key] = mean
            result[key + ' CI95 Lower'] = lower
            result[key + ' CI95 Upper'] = upper
        summary.append(result)
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(output_dir / 'Barrier_Comparison_10runs.csv', index=False)
    print('\nBarrier comparison summary (10 seeds per threshold):')
    show = [
        'Threshold', 'Throughput (tx/1000ms)', 'Latency Mean (ms)',
        'Total Backlog Mean', 'EC Round Duration Mean (ms)',
        'Max Monetary Deviation',
    ]
    print(summary_df[show].to_string(index=False, float_format=lambda v: f'{v:,.2f}'))
    print('Results saved in:', output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-test', action='store_true',
                        help='Run a small, separate 3 x 2 sanity check.')
    parser.add_argument('--reset', action='store_true',
                        help='Discard previously saved summary rows.')
    args = parser.parse_args()

    output_dir = Path(__file__).with_name(
        'barrier_smoketest_fair' if args.smoke_test else 'barrier_30runs_fair'
    )
    output_dir.mkdir(exist_ok=True)
    engine = load_engine()

    output_csv = output_dir / 'barrier_all_30_runs.csv'
    if output_csv.exists() and not args.reset:
        rows = pd.read_csv(output_csv).to_dict('records')
    else:
        rows = []

    seeds = range(42, 44) if args.smoke_test else SEEDS
    # ------------------------------------------------------------
    # Outer loop: 70%, 80%, 90%; inner loop: ten different seeds.
    # ------------------------------------------------------------
    for threshold in THRESHOLDS:
        for seed in seeds:
            if any(abs(float(row['Threshold']) - threshold) < 1e-8
                   and int(row['Seed']) == seed for row in rows):
                print(f'Skipping completed Barrier={threshold:.0%}, seed={seed}')
                continue
            print(f'Running Barrier={threshold:.0%}, N_AC={10 if args.smoke_test else N_AC}, '
                  f'seed={seed}', flush=True)
            data = simulate(engine, threshold, seed, smoke_test=args.smoke_test)
            result = analyze(data)
            rows.append(result)
            save_summary(rows, output_dir, partial=True)
            print(f"  EC rounds={result['Number of EC Rounds']:,}, "
                  f"throughput={result['Throughput (tx/1000ms)']:,.2f} tx/1000ms, "
                  f"latency={result['Latency Mean (ms)']:,.2f} ms, "
                  f"max deviation={result['Max Monetary Deviation']}", flush=True)
            del data
            gc.collect()

    if args.smoke_test:
        print('\nSmoke test finished:', output_csv)
    else:
        save_summary(rows, output_dir)


if __name__ == '__main__':
    main()
