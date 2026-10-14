#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 3 / Table 4: 3 AC sizes x 10 independent seeds (30 runs).

Place beside bea_cbdc_basic.py and run:
    python3 run_bea_cbdc_tables34_30_simple.py

Uses the unchanged simulation engine. Prints the progress at EC rounds
100, 200, ..., 900 (every 100 rounds), and collects results in memory
instead of writing a very large NPZ file at the end of each run.
"""

from contextlib import redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import gc
import random
import sys

import numpy as np
import pandas as pd


ENGINE = Path(__file__).with_name('bea_cbdc_basic.py')
OUTPUT = Path(__file__).with_name('tables34_30runs')
AC_SIZES = (1000, 500, 100)
SEEDS = range(42, 52)
T_CRITICAL_95 = 2.262157162740992  # df = 9, two-sided Student-t


class ProgressEvery100Rounds:
    """Display the original simulator's progress only every 100 EC rounds."""

    def __init__(self, terminal):
        self.terminal = terminal
        self.pending_text = ''

    def write(self, text):
        self.pending_text += text
        while '\n' in self.pending_text:
            line, self.pending_text = self.pending_text.split('\n', 1)
            if not line.startswith('Round '):
                continue
            try:
                round_no = int(line.split('|', 1)[0].split()[1])
            except (IndexError, ValueError):
                continue
            if round_no % 100 == 0:
                self.terminal.write(line + '\n')
                self.terminal.flush()

    def flush(self):
        self.terminal.flush()


def load_engine():
    spec = spec_from_file_location('bea_cbdc_engine', ENGINE)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module  # required for @dataclass
    spec.loader.exec_module(module)
    return module


def simulate(engine, n_ac, seed):
    cfg = engine.Config()
    cfg.N_AC = n_ac
    cfg.seed = seed
    cfg.Flag_Burst = False
    cfg.P_Fail_AC = 0.0
    cfg.log_level = 0

    # Seed transaction generation as well as settlement simulation.
    random.seed(seed)
    np.random.seed(seed)
    requests = engine.initialize_request_schedule(cfg)
    transactions = np.empty((int(requests.sum()), 5), dtype=np.int32)
    ids_per_ac = [np.empty(0, dtype=np.int32) for _ in range(n_ac)]
    engine.generate_Total_Tx(cfg, requests, transactions)
    engine.classify_Total_Tx_per_AC(cfg, transactions, ids_per_ac)

    matrix = np.full((n_ac, n_ac), -1, dtype=np.int64)
    backlog = np.zeros((cfg.N_Round - 20, n_ac), dtype=np.int32)
    balances = np.zeros((cfg.N_Round, n_ac), dtype=np.int64)
    pending = np.zeros((cfg.N_Round, n_ac), dtype=np.int64)

    # The original engine writes one hard-coded, very large NPZ filename.
    # Capture precisely those arrays without compressing or saving the NPZ.
    data = {}
    original_save = np.savez_compressed

    def capture_result(_filename, **arrays):
        data.update(arrays)

    try:
        np.savez_compressed = capture_result
        with redirect_stdout(ProgressEvery100Rounds(sys.stdout)):
            engine.run_simulation(
                cfg, transactions, ids_per_ac, matrix,
                backlog, balances, pending,
            )
    finally:
        np.savez_compressed = original_save

    if not data:
        raise RuntimeError('The simulation ended without producing results.')
    return data


def analyze(data):
    """Same evaluation windows and metrics as the uploaded analysis script."""
    cfg = data['cfg']
    tx = data['Total_Tx']
    start_time = 10 * cfg['Delta_R']
    end_time = (cfg['N_Round'] - 10) * cfg['Delta_R']
    requested = tx[:, 3]
    completed = tx[:, 4]
    selected = ((requested >= start_time) & (requested < end_time)
                & (completed >= 0))
    latencies = completed[selected].astype(np.int64) - requested[selected]

    round_throughput = data['completed_tx_per_round']
    backlog = data['backlog']
    valid = backlog >= 0
    system_backlog = np.where(valid, backlog, 0).sum(axis=1)
    report = data['report_success']
    readiness = data['readiness_success']
    system_balances = data['Sum_balance'].sum(axis=1, dtype=np.int64)
    system_pending = data['Sum_pending_balance'].sum(axis=1, dtype=np.int64)
    monetary_total = system_balances + system_pending

    result = {
        'Throughput Mean': float(np.mean(round_throughput)),
        'Throughput SD': float(np.std(round_throughput)),
        'Latency Mean (ms)': float(np.mean(latencies)),
        'Latency SD (ms)': float(np.std(latencies)),
        'Latency P95 (ms)': float(np.percentile(latencies, 95)),
        'Latency P99 (ms)': float(np.percentile(latencies, 99)),
        'Backlog/AC Mean': float(np.mean(backlog[valid])),
        'Total Backlog Mean': float(np.mean(system_backlog)),
        'Total Backlog Maximum': int(np.max(system_backlog)),
        'Report Mean': float(np.mean(report)),
        'Report SD': float(np.std(report)),
        'Readiness Mean': float(np.mean(readiness)),
        'Readiness SD': float(np.std(readiness)),
        'Initial Total CBDC': int(monetary_total[0]),
        'Pending Mean': float(np.mean(system_pending)),
        'Max Monetary Deviation': int(
            np.max(np.abs(monetary_total.astype(object) - int(monetary_total[0])))
        ),
    }
    return result


def mean_and_ci(values):
    values = np.asarray(values, dtype=np.float64)
    mean = float(values.mean())
    sem = float(values.std(ddof=1) / np.sqrt(len(values)))
    half_width = T_CRITICAL_95 * sem
    return mean, mean - half_width, mean + half_width


def save_tables(all_runs):
    df = pd.DataFrame(all_runs)
    df.to_csv(OUTPUT / 'all_30_runs.csv', index=False)

    baseline = df[df['N_AC'] == AC_SIZES[0]]
    table3 = []
    for metric in (
        'Throughput Mean', 'Throughput SD',
        'Latency Mean (ms)', 'Latency SD (ms)',
        'Latency P95 (ms)', 'Latency P99 (ms)',
        'Backlog/AC Mean', 'Total Backlog Mean', 'Total Backlog Maximum',
        'Report Mean', 'Report SD', 'Readiness Mean', 'Readiness SD',
        'Initial Total CBDC', 'Pending Mean', 'Max Monetary Deviation',
    ):
        mean, lower, upper = mean_and_ci(baseline[metric])
        table3.append({'Metric': metric, 'Mean': mean,
                       'CI95_Lower': lower, 'CI95_Upper': upper})
    pd.DataFrame(table3).to_csv(OUTPUT / 'Table3_10runs.csv', index=False)

    table4 = []
    for n_ac in AC_SIZES:
        group = df[df['N_AC'] == n_ac]
        row = {'N_AC': n_ac}
        for metric in (
            'Backlog/AC Mean', 'Total Backlog Mean',
            'Latency Mean (ms)', 'Pending Mean',
        ):
            mean, lower, upper = mean_and_ci(group[metric])
            row[metric] = mean
            row[metric + ' CI95 Lower'] = lower
            row[metric + ' CI95 Upper'] = upper
        table4.append(row)
    pd.DataFrame(table4).to_csv(OUTPUT / 'Table4_10runs.csv', index=False)
    print('\nTable 3 and Table 4 saved in:', OUTPUT)


def main():
    OUTPUT.mkdir(exist_ok=True)
    engine = load_engine()
    all_runs = []

    # --------------------------------------------------------
    # Main experiment: outer N_AC loop, inner random-seed loop
    # --------------------------------------------------------
    for n_ac in AC_SIZES:
        for seed in SEEDS:
            print(f'Running N_AC={n_ac}, seed={seed}', flush=True)
            data = simulate(engine, n_ac, seed)
            result = analyze(data)
            result.update({'N_AC': n_ac, 'Seed': seed})
            all_runs.append(result)
            pd.DataFrame(all_runs).to_csv(
                OUTPUT / 'all_30_runs.csv', index=False
            )
            print(f"  throughput={result['Throughput Mean']:.2f}, "
                  f"latency={result['Latency Mean (ms)']:.2f} ms", flush=True)
            del data
            gc.collect()

    save_tables(all_runs)


if __name__ == '__main__':
    main()