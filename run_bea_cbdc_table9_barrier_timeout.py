#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 9: barrier WITH independent T0/T2 timeouts under temporary AC failure.

This is a SINGLE-RUN, scenario-based experiment (seed 42) for each of
q=0.7, 0.8 and 0.9, NOT a 10-seed statistical experiment.

Use the matching engine 'bea_cbdc_basic_barrier_table9_timeout.py' from
this package in the same directory. This engine retains the original
settlement code and expresses the reference AC failure windows in physical
1,000-ms periods despite variable barrier EC round lengths.

Configuration matches the Section 5.4 / Table 6 temporary failure model:
  N_AC=1000; N_User=1e8; N_Round=1000; Delta_R=1000 ms;
  500 randomly chosen ACs fail once, start in rounds 100..800,
  duration 20..100 fixed-cutoff rounds (each 1000 ms).
  No burst traffic; system-wide arrivals at 100 requests/ms.

Usage:
  python run_bea_cbdc_table9_barrier_timeout.py
  python run_bea_cbdc_table9_barrier_timeout.py --q 0.9
  python run_bea_cbdc_table9_barrier_timeout.py --smoke-test

Results: table9_barrier_timeout/{Table9_Barrier_Timeout.csv,
Table9_Barrier_Timeout_Rounds_q*.csv, Table9_Failure_Schedule.csv}.

T0/T2 timeouts by q (ms):
  q=0.7: 10 / 443
  q=0.8: 20 / 510
  q=0.9: 100 / 616
Each stage advances at the earlier of the quorum or its own timeout.
Only reports received by that point participate; there is no global round cap.

The Table 9 results describe one scenario, not repeated-run confidence
intervals. Mean transaction latency concerns COMPLETED transactions only;
uncompleted counts are reported separately.
"""

import argparse
import csv
import gc
import math
import random
import sys
from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np

ENGINE_FILE = Path(__file__).with_name('bea_cbdc_basic_barrier_table9_timeout.py')
THRESHOLDS = (0.7, 0.8, 0.9)
SEED = 42
CHUNK_SIZE = 1_000_000


def load_engine():
    if not ENGINE_FILE.is_file():
        raise FileNotFoundError(f'Engine not found: {ENGINE_FILE}')
    spec = spec_from_file_location('bea_cbdc_table9_no_timeout_engine', ENGINE_FILE)
    engine = module_from_spec(spec)
    sys.modules[spec.name] = engine  # Needed for dataclasses
    spec.loader.exec_module(engine)
    return engine


def save_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class LatencyAccumulator:
    count: int = 0
    total: int = 0
    sum_sq: float = 0.0
    frequencies: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))

    def add(self, latency_ms):
        lat = np.asarray(latency_ms, dtype=np.int64)
        if not lat.size:
            return
        if np.any(lat < 0):
            raise AssertionError('Negative transaction latency.')
        self.count += int(lat.size)
        self.total += int(np.sum(lat, dtype=np.int64))
        self.sum_sq += float(np.sum(lat.astype(np.float64)**2))
        counts = np.bincount(lat)
        if counts.size > self.frequencies.size:
            self.frequencies = np.pad(self.frequencies,
                                      (0, counts.size - self.frequencies.size))
        self.frequencies[:counts.size] += counts

    def percentile(self, p):
        if not self.count:
            return float('nan')
        rank = (self.count - 1) * p / 100.0
        lo, hi = math.floor(rank), math.ceil(rank)
        cumulative = np.cumsum(self.frequencies)
        v_lo = int(np.searchsorted(cumulative, lo + 1))
        v_hi = int(np.searchsorted(cumulative, hi + 1))
        return v_lo + (rank - lo) * (v_hi - v_lo)

    def as_dict(self, prefix):
        if not self.count:
            return {prefix + ' Count': 0, prefix + ' Mean (ms)': '',
                    prefix + ' SD (ms)': '', prefix + ' P95 (ms)': '',
                    prefix + ' P99 (ms)': ''}
        mean = self.total / self.count
        variance = max(0.0, self.sum_sq / self.count - mean**2)
        return {prefix + ' Count': self.count, prefix + ' Mean (ms)': mean,
                prefix + ' SD (ms)': math.sqrt(variance),
                prefix + ' P95 (ms)': self.percentile(95),
                prefix + ' P99 (ms)': self.percentile(99)}


def analyze_transactions(data):
    cfg = data['cfg']
    tx = data['Total_Tx']
    users_per_ac = cfg['N_User'] // cfg['N_AC']
    failed_lookup = np.zeros(cfg['N_AC'], dtype=np.bool_)
    failed_lookup[list(data['failure_schedule'])] = True

    all_completed = LatencyAccumulator()
    never_failed_pairs = LatencyAccumulator()
    failure_involved = LatencyAccumulator()
    eval_completed = LatencyAccumulator()
    n_completed_eval_interval = 0
    n_completed = 0
    eval_start = 10 * cfg['Delta_R']
    eval_end = (cfg['N_Round'] - 10) * cfg['Delta_R']
    horizon = data['Traffic_Horizon_ms']

    # Chunking avoids large additional arrays when N_Tx is about 1e8.
    for start in range(0, len(tx), CHUNK_SIZE):
        piece = tx[start:start + CHUNK_SIZE]
        requested = piece[:, 3]
        completed = piece[:, 4]
        ok = completed >= 0
        n_completed += int(np.count_nonzero(ok))
        n_completed_eval_interval += int(np.count_nonzero(
            (completed >= eval_start) & (completed < eval_end)))
        if not np.any(ok):
            continue
        times = (completed[ok].astype(np.int64)
                 - requested[ok].astype(np.int64))
        all_completed.add(times)
        sources = piece[ok, 0] // users_per_ac
        destinations = piece[ok, 1] // users_per_ac
        involved = failed_lookup[sources] | failed_lookup[destinations]
        never_failed_pairs.add(times[~involved])
        failure_involved.add(times[involved])

        valid_eval = ((requested[ok] >= eval_start)
                      & (requested[ok] < eval_end)
                      & (completed[ok] < horizon))
        eval_completed.add(times[valid_eval])

    return dict(
        generated_transactions=len(tx),
        completed_transactions=n_completed,
        unfinished_transactions=len(tx) - n_completed,
        normalized_throughput=n_completed_eval_interval * cfg['Delta_R']
                              / (eval_end - eval_start),
        all_completed=all_completed,
        never_failed_pairs=never_failed_pairs,
        failure_involved=failure_involved,
        eval_completed=eval_completed,
    )


def weighted_mean(values, weights):
    total = sum(weights)
    return float(np.average(values, weights=weights)) if total > 0 else float('nan')


def analyze_rounds(data):
    cfg = data['cfg']
    rows = data['round_metrics']
    start = 10 * cfg['Delta_R']
    end = (cfg['N_Round'] - 10) * cfg['Delta_R']
    weights = [max(0, min(r['Next_Round_Open_ms'], end)
                   - max(r['Round_Open_ms'], start)) for r in rows]
    indices = [i for i, w in enumerate(weights) if w > 0]
    if not indices:
        raise RuntimeError('No EC round overlaps the evaluation interval.')
    weights = [weights[i] for i in indices]
    sampled = [rows[i] for i in indices]
    initial_cbdc = rows[0]['Total_CBDC']
    return {
        'T0 Timeout (ms)': rows[0]['T0_Timeout_ms'],
        'T2 Timeout (ms)': rows[0]['T2_Timeout_ms'],
        'T0 Timeout Count': sum(r['T0_Timeout_Triggered'] for r in rows),
        'T2 Timeout Count': sum(r['T2_Timeout_Triggered'] for r in rows),
        'T0 Quorum Met Count': sum(r['T0_Quorum_Met'] for r in rows),
        'T2 Quorum Met Count': sum(r['T2_Quorum_Met'] for r in rows),
        'EC Round Duration Mean (ms)': float(np.mean(
            [r['Round_Duration_ms'] for r in sampled])),
        'T0 Wait Mean (ms)': float(np.mean(
            [r['Report_Wait_ms'] for r in sampled])),
        'T2 Wait Mean (ms)': float(np.mean(
            [r['Readiness_Wait_ms'] for r in sampled])),
        'Total Backlog Mean': weighted_mean(
            [r['Total_Backlog'] for r in sampled], weights),
        'Backlog/Active AC Mean': weighted_mean(
            [r['Backlog_per_Active_AC'] for r in sampled], weights),
        'Pending CBDC Mean': weighted_mean(
            [r['Pending_CBDC'] for r in sampled], weights),
        'Report Success Mean': float(np.mean(
            [r['Report_Success'] for r in sampled])),
        'Readiness Success Given Report Mean': float(np.mean(
            [r['Readiness_Success_Given_Report'] for r in sampled])),
        'Unavailable AC Mean': weighted_mean(
            [r['Unavailable_ACs'] for r in sampled], weights),
        'Unavailable AC Max': max(r['Unavailable_ACs'] for r in rows),
        'Number of EC Rounds': data['N_EC_Rounds'],
        'Simulation End (ms)': data['Simulation_End_ms'],
        'Max Monetary Deviation': max(abs(r['Total_CBDC'] - initial_cbdc)
                                      for r in rows),
    }


def simulate(engine, q, smoke_test=False, progress_every=100):
    cfg = engine.Config()
    cfg.barrier_threshold = q
    cfg.seed = SEED
    cfg.N_AC = 1000
    cfg.N_User = 100_000_000
    cfg.N_Round = 1000
    cfg.Delta_R = 1000
    cfg.lambda_tx = 100.0
    cfg.Flag_Burst = False
    cfg.P_Fail_AC = 0.5
    cfg.R_Fail_Start = 100
    cfg.R_Fail_End = 800
    cfg.Min_Fail_Duration = 20
    cfg.Max_Fail_Duration = 100
    cfg.log_level = 0
    if smoke_test:
        cfg.N_AC = 30
        cfg.N_User = 3_000
        cfg.N_Round = 80
        cfg.lambda_tx = 0.25
        cfg.N_Tx_per_AC_block = 400
        cfg.R_Fail_Start = 10
        cfg.R_Fail_End = 60
        cfg.Min_Fail_Duration = 1
        cfg.Max_Fail_Duration = 2

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    requests = engine.initialize_request_schedule(cfg)
    tx = np.empty((int(requests.sum()), 5), dtype=np.int32)
    ids_per_ac = [np.empty(0, dtype=np.int32) for _ in range(cfg.N_AC)]
    engine.generate_Total_Tx(cfg, requests, tx)
    engine.classify_Total_Tx_per_AC(cfg, tx, ids_per_ac)
    matrix = np.full((cfg.N_AC, cfg.N_AC), -1, dtype=np.int64)
    return engine.run_barrier_timeout_simulation(
        cfg, tx, ids_per_ac, matrix, progress_every=progress_every)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--q', type=float, choices=THRESHOLDS,
                   help='Run only this threshold; default all three.')
    p.add_argument('--smoke-test', action='store_true', help='Small validation run.')
    p.add_argument('--reset', action='store_true', help='Recompute existing rows.')
    p.add_argument('--progress-every', type=int, default=100)
    args = p.parse_args()

    folder = Path(__file__).with_name(
        'table9_barrier_timeout_smoke' if args.smoke_test
        else 'table9_barrier_timeout')
    folder.mkdir(exist_ok=True)
    summary_path = folder / 'Table9_Barrier_Timeout.csv'
    existing = []
    if summary_path.exists() and not args.reset:
        with summary_path.open(encoding='utf-8', newline='') as f:
            existing = list(csv.DictReader(f))
    engine = load_engine()
    selected = (args.q,) if args.q is not None else THRESHOLDS

    for q in selected:
        if any(abs(float(r['q']) - q) < 1e-8 and r.get('Seed') == str(SEED)
               and r.get('Status') == 'COMPLETED' for r in existing):
            print(f'Skipping q={q:.1f}: already completed.', flush=True)
            continue
        print(f'\nTable 9 | WITH TIMEOUT | q={q:.1f} | seed={SEED}'
              f' | P_Fail_AC=0.50 | N_AC={30 if args.smoke_test else 1000}',
              flush=True)
        data = simulate(engine, q, smoke_test=args.smoke_test,
                        progress_every=args.progress_every)

        schedule = data['failure_schedule']
        schedule_rows = [
            {'AC_ID': ac_id, 'Failure_Start_Reference_Round': spans[0][0],
             'Failure_End_Reference_Round': spans[0][1],
             'Failure_Start_ms': spans[0][0] * data['cfg']['Delta_R'],
             'Failure_End_Exclusive_ms': (spans[0][1] + 1) * data['cfg']['Delta_R']}
            for ac_id, spans in sorted(schedule.items())]
        schedule_path = folder / 'Table9_Failure_Schedule.csv'
        if schedule_path.is_file():
            with schedule_path.open(encoding='utf-8', newline='') as f:
                old = list(csv.DictReader(f))
            if old != [{k: str(v) for k, v in row.items()} for row in schedule_rows]:
                raise AssertionError('Failure schedule differs across thresholds.')
        else:
            save_csv(schedule_path, schedule_rows)

        times = analyze_transactions(data)
        rounds = analyze_rounds(data)
        result = {
            'Mode': 'Barrier-WithTimeout',
            'q': q, 'Seed': SEED, 'Status': 'COMPLETED', 'Stall Reason': '',
            'N_AC': data['cfg']['N_AC'],
            'Number of Selected Failed ACs': len(schedule),
            'Generated Requests': times['generated_transactions'],
            'Completed Requests': times['completed_transactions'],
            'Unfinished Requests': times['unfinished_transactions'],
            'Throughput (tx/1000ms)': times['normalized_throughput'],
            **times['all_completed'].as_dict('All Completed'),
            **times['never_failed_pairs'].as_dict('Never-Failed AC Pair'),
            **times['failure_involved'].as_dict('Failure-Involved'),
            **times['eval_completed'].as_dict('Evaluation-Window Completed'),
            **rounds,
        }
        save_csv(folder / f'Table9_Barrier_Timeout_Rounds_q{q:.1f}.csv',
                 data['round_metrics'])
        existing = [r for r in existing
                    if not (float(r['q']) == q and r.get('Seed') == str(SEED))]
        existing.append(result)
        existing.sort(key=lambda r: float(r['q']))
        # Reconcile field layout if pre-existing STALLED rows have fewer fields.
        all_fields = list(dict.fromkeys(k for row in existing for k in row))
        with summary_path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_fields)
            writer.writeheader()
            writer.writerows(existing)
        print(f"Completed q={q:.1f}: T0 timeout count={rounds['T0 Timeout Count']}, "
              f"T2 timeout count={rounds['T2 Timeout Count']}; throughput="
              f"{result['Throughput (tx/1000ms)']:,.2f}, "
              f"latency={result['All Completed Mean (ms)']:,.2f} ms, "
              f"backlog={result['Total Backlog Mean']:,.2f}, "
              f"monetary deviation={result['Max Monetary Deviation']}",
              flush=True)
        del data
        gc.collect()

    print(f'\nSaved results to: {folder}', flush=True)


if __name__ == '__main__':
    main()
