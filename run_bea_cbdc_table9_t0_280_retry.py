#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 9 re-experiment: six barrier configurations ONLY (no cutoff run).

Comparison baseline: use the existing Table 6 time-based cutoff results.
Barrier modes: q=0.7/0.8/0.9 each with and without timeout.
T0 uses ceil(q * N_AC); T2 uses ceil(q * N_T0), with N_T0
being the number of T0 participants. Timeout barriers use T0=280ms for
q=0.7/0.8/0.9 while retaining the original T2 timeout values.
All six runs share the destination-fair transaction queue and archived
Table 9 AC outage schedule (500 ACs each failing once).

Run:
  python -u run_bea_cbdc_table9_t0_280_retry.py --list
  python -u run_bea_cbdc_table9_t0_280_retry.py --smoke-test
  python -u run_bea_cbdc_table9_t0_280_retry.py
  python -u run_bea_cbdc_table9_t0_280_retry.py --mode timeout --q 0.9
  python -u run_bea_cbdc_table9_t0_280_retry.py --stress-test

This script NEVER simulates a time-based cutoff. The common base module
contains AC/transaction helpers inherited from the original simulator.
"""

import argparse
import csv
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
THRESHOLDS = (0.7, 0.8, 0.9)
SEED = 42


def load_module(module_name, filename):
    path = HERE / filename
    if not path.is_file():
        raise FileNotFoundError(f'{filename} missing. Place all necessary files together in {HERE}')
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def save_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for row in rows for k in row.keys()))
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def failure_schedule(cfg, smoke=False):
    """Return one identical outage schedule for all six barrier runs.

    For full-scale operation, the source CSV is mandatory and constitutes
    the historical Table 9 failure schedule. The independently generated
    smoke schedule is deliberately smaller and is NOT the source CSV.
    """
    if smoke:
        rng = random.Random(SEED)
        selected = rng.sample(range(cfg.N_AC), int(round(cfg.N_AC*cfg.P_Fail_AC)))
        return dict(sorted((ac_id, [(start := rng.randint(cfg.R_Fail_Start,
                                cfg.R_Fail_End),
                                min(start + rng.randint(cfg.Min_Fail_Duration,
                                          cfg.Max_Fail_Duration) - 1,
                                    cfg.N_Round - 1))]) for ac_id in selected))
    src = HERE / 'Table9_T0_280_Retry_Failure_Schedule_Input.csv'
    if not src.is_file():
        raise FileNotFoundError(f'Missing archived Table 9 failure schedule: {src}')
    result = {}
    with src.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ac_id = int(row['AC_ID'])
            start = int(row['Failure_Start_Reference_Round'])
            end = int(row['Failure_End_Reference_Round'])
            if not (0 <= ac_id < cfg.N_AC and
                    cfg.R_Fail_Start <= start <= cfg.R_Fail_End and
                    cfg.Min_Fail_Duration <= end-start+1 <= cfg.Max_Fail_Duration
                    and end < cfg.N_Round):
                raise ValueError(f'Invalid AC outage in {src}: {row}')
            if (int(row['Failure_Start_ms']) != start*cfg.Delta_R or
                    int(row['Failure_End_Exclusive_ms']) != (end+1)*cfg.Delta_R):
                raise ValueError('Failure CSV timestamps are inconsistent')
            if ac_id in result:
                raise ValueError(f'AC {ac_id} appears more than once in {src}')
            result[ac_id] = [(start,end)]
    n = int(round(cfg.N_AC * cfg.P_Fail_AC))
    if len(result) != n:
        raise ValueError(f'Expected exactly {n} failed ACs, saw {len(result)}')
    return dict(sorted(result.items()))


def setup_cfg(base, smoke=False, stress=False):
    cfg = base.Config()
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
    if smoke:
        cfg.N_AC = 40
        cfg.N_User = 4000
        cfg.N_Round = 80
        cfg.lambda_tx = 0.25
        cfg.N_Tx_per_AC_block = 12 if stress else 400
        cfg.R_Fail_Start = 10
        cfg.R_Fail_End = 45
        cfg.Min_Fail_Duration = 5
        cfg.Max_Fail_Duration = 20
    return cfg


def generate_transactions(base, cfg):
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    requests = base.initialize_request_schedule(cfg)
    transactions = np.empty((int(requests.sum()), 5), dtype=np.int32)
    ids_per_ac = [np.empty(0, dtype=np.int32) for _ in range(cfg.N_AC)]
    base.generate_Total_Tx(cfg, requests, transactions)
    base.classify_Total_Tx_per_AC(cfg, transactions, ids_per_ac)
    matrix = np.full((cfg.N_AC, cfg.N_AC), -1, dtype=np.int64)
    return transactions, ids_per_ac, matrix


def summarize(data, round_metrics, analysis, mode, q, schedule):
    tx = analysis.analyze_transactions(data)
    result = {
        'Mode': {'barrier':'Barrier-NoTimeout',
                 'timeout':'Barrier-WithTimeout'}[mode],
        'q': '' if q is None else q,
        'Seed': SEED,
        'Status': data['Status'],
        'Stop Reason': data['Stop_Reason'],
        'N_AC': data['cfg']['N_AC'],
        'Failed ACs': len(schedule),
        'Generated Requests': tx['generated_transactions'],
        'Completed Requests': tx['completed_transactions'],
        'Unfinished Requests': tx['unfinished_transactions'],
        'Throughput (tx/1000ms)': tx['normalized_throughput'],
        **tx['all_completed'].as_dict('All Completed'),
        **tx['never_failed_pairs'].as_dict('Never-Failed AC Pair'),
        **tx['failure_involved'].as_dict('Failure-Involved'),
        **tx['eval_completed'].as_dict('Evaluation-Window Completed'),
        **round_metrics,
    }
    result['T0 Timeout Count'] = sum(r['T0_Timeout_Triggered']
                                    for r in data['round_metrics'])
    result['T2 Timeout Count'] = sum(r['T2_Timeout_Triggered']
                                    for r in data['round_metrics'])
    result['Max T0 Wait (ms)'] = max((r['Report_Wait_ms']
                                     for r in data['round_metrics']), default='')
    result['Max T2 Wait (ms)'] = max((r['Readiness_Wait_ms']
                                     for r in data['round_metrics']), default='')
    result.update(data['Retry_Audit'])
    result['Pending Barrier Start (ms)'] = data['Pending_Barrier_Start_ms']
    result['Next Quorum Time (ms)'] = data['Pending_Barrier_Next_Quorum_ms']
    if mode == 'timeout':
        result['T0 Timeout (ms)'], result['T2 Timeout (ms)'] = (
            __import__('bea_cbdc_table9_t0_280_retry_barrier').TIMEOUTS[q])
    if result['Max Monetary Deviation'] != 0:
        raise AssertionError('CBDC conservation invariant was violated')
    return result


def pair_key(item):
    return (str(item['Mode']), str(item.get('q', '')))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=('all','barrier','timeout'),
                        default='all')
    parser.add_argument('--q', type=float, choices=THRESHOLDS)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--stress-test', action='store_true',
                        help='Small high-utilization queue-saturation regression')
    parser.add_argument('--reset', action='store_true',
                        help='Repeat selected runs, replacing their existing results')
    parser.add_argument('--progress-every', type=int, default=100)
    parser.add_argument('--audit-retries', action='store_true',
                        help='Write per-AC T0 retry/notification timeline CSV')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.stress_test:
        args.smoke_test = True
    if args.q is not None and args.mode not in ('barrier','timeout'):
        parser.error('--q can only be used with --mode barrier/timeout')

    engine = load_module('bea_cbdc_table9_t0_280_retry_barrier', 'bea_cbdc_table9_t0_280_retry_barrier.py')
    base = engine.base
    analysis = load_module('table9_t0_280_retry_analysis', 'table9_t0_280_retry_analysis.py')
    cfg = setup_cfg(base, smoke=args.smoke_test, stress=args.stress_test)
    schedule = failure_schedule(cfg, smoke=args.smoke_test)
    concurrent = np.zeros(cfg.N_Round, dtype=np.int32)
    for one in schedule.values():
        a,b = one[0]
        concurrent[a:b+1] += 1
    max_count = int(concurrent.max())
    max_round = int(np.argmax(concurrent))
    mean_count = float(concurrent.mean())
    print(f'Table 9: T0 280ms in timeout mode; relative T2 quorum: {cfg.N_AC} ACs, {len(schedule)} failed once; '
          f'failure starts {cfg.R_Fail_Start}-{cfg.R_Fail_End} sec; '
          f'duration {cfg.Min_Fail_Duration}-{cfg.Max_Fail_Duration} sec')
    print(f'  Mean concurrent failed ACs: {mean_count:.2f}; '
          f'peak: {max_count} (reference second {max_round})')
    if not args.smoke_test:
        if max_count != 56:
            raise AssertionError(f'Archived Table 9 peak outage count drifted: {max_count}')
    jobs = [(mode,q) for mode in ('barrier','timeout')
            for q in THRESHOLDS]
    if args.mode != 'all':
        jobs = [(m,q) for m,q in jobs if m == args.mode and
                (args.q is None or q == args.q)]
    print('  Selected runs: '+', '.join(m+(f' q={q}' if q is not None else '')
                                       for m,q in jobs))
    if args.list:
        return

    out = HERE / (f'table9_t0_280_retry_barrier_6runs' + ('_stress' if args.stress_test else '_smoke' if args.smoke_test else ''))
    out.mkdir(exist_ok=True)
    schedule_lines = [
        {'AC_ID': acid, 'Failure_Start_s': starts[0][0],
         'Failure_End_Exclusive_s': starts[0][1]+1,
         'Failure_Duration_s': starts[0][1]-starts[0][0]+1}
        for acid, starts in schedule.items()
    ]
    schedule_fingerprint = hashlib.sha256(json.dumps(schedule_lines,
                                    sort_keys=True).encode()).hexdigest()
    metadata = {
        'experiment': 'Table 9 six barriers, T0=280ms for timed variants, T2 relative to T0 participants, destination-fair queues',
        't2_quorum_definition': 'ceil(q * N_T0)',
        't2_quorum_basis': 'T0_PARTICIPANTS',
        'queue_policy': 'destination-fair-round-robin-v1',
        't0_quorum_definition': 'ceil(q * N_AC)',
        'failure_schedule_source': 'Table9_T0_280_Retry_Failure_Schedule_Input.csv' if not args.smoke_test else 'deterministic smoke schedule',
        'capacity_per_local_round': cfg.N_Tx_per_AC_block,
        'seed': SEED, 'N_AC': cfg.N_AC, 'N_User': cfg.N_User,
        'N_Round': cfg.N_Round, 'Delta_R_ms': cfg.Delta_R,
        'lambda_tx': cfg.lambda_tx, 'P_Fail_AC': cfg.P_Fail_AC,
        'R_Fail_Start': cfg.R_Fail_Start, 'R_Fail_End': cfg.R_Fail_End,
        'Min_Fail_Duration': cfg.Min_Fail_Duration,
        'Max_Fail_Duration': cfg.Max_Fail_Duration,
        'n_selected': len(schedule), 'mean_concurrent_failed': mean_count,
        'max_concurrent_failed': max_count, 'max_failed_at_s': max_round,
        'failure_schedule_sha256': schedule_fingerprint,
        'T0_T2_Timeouts_ms': {str(q):list(engine.TIMEOUTS[q]) for q in THRESHOLDS},
        'run_modes': 'Barrier-NoTimeout and Barrier-WithTimeout only; no time-based cutoff',
        'cutoff_reference': 'Existing Table 6 results; no cutoff simulation in this run',
        'retry_timing_policy': ('Prepared-but-late T0 report waits until T1 '
            'matrix announcement plus receive delay (t2); idle/offline '
            'not-yet-prepared candidates retain previous next_start'),
        'barrier_engine_revision': 't0_280_retry_v1',
    }
    meta_path = out/'Table9_T0_280_Retry_Scenario.json'
    same_scenario = True
    if meta_path.exists():
        prev = json.loads(meta_path.read_text(encoding='utf-8'))
        same_scenario = prev == metadata
        if not same_scenario and not args.reset:
            raise RuntimeError('Output directory contains a different scenario. '
                               'Move it aside or run --reset.')
    meta_path.write_text(json.dumps(metadata, indent=2)+'\n',encoding='utf-8')
    save_csv(out/'Table9_T0_280_Retry_Failure_Schedule.csv', schedule_lines)
    save_csv(out/'Table9_T0_280_Retry_Concurrent_Failures.csv', [
        {'Reference_Second':i, 'Concurrent_Failed_ACs':int(n)}
        for i,n in enumerate(concurrent)])
    summary_path = out/'Table9_T0_280_Retry_Barrier_All_6.csv'
    summary = []
    if summary_path.exists() and same_scenario:
        with summary_path.open(newline='',encoding='utf-8') as f:
            summary = list(csv.DictReader(f))

    for mode,q in jobs:
        label = {'barrier':'Barrier-NoTimeout',
                 'timeout':'Barrier-WithTimeout'}[mode]
        target = (label, '' if q is None else str(q))
        if not args.reset and any(pair_key(x)==target and x.get('Status')
                                  in ('COMPLETED','OBSERVATION_END','BLOCKED_AT_HORIZON')
                                  for x in summary):
            print(f'  Already recorded: {label} q={q}. Skipping.')
            continue
        run_cfg = setup_cfg(base, smoke=args.smoke_test, stress=args.stress_test)
        if q is not None:
            run_cfg.barrier_threshold = q
        print(f'Running {label} q={q}; one run, seed {SEED} ...', flush=True)
        print('  Generating shared synthetic transactions; this step may be lengthy.', flush=True)
        tx, ids, matrix = generate_transactions(base, run_cfg)
        print(f'  Transaction generation finished: {len(tx):,} requests; starting settlement.',
              flush=True)
        data = None
        try:
            data = engine.run_barrier_table9(
                run_cfg, tx, ids, matrix, failure_schedule=schedule,
                with_timeout=(mode == 'timeout'),
                progress_every=args.progress_every,
                audit_retries=args.audit_retries)
            round_summary = analysis.analyze_rounds(data)
            if args.audit_retries and data['T0_Retry_Trace']:
                save_csv(out / f'Table9_T0_280_Retry_T0_Trace_{mode}_q{q:.1f}.csv',
                         data['T0_Retry_Trace'])
            if data['Retry_Audit']['Retry_Timing_Violations']:
                raise AssertionError('The T0 retry time invariant failed')
            save_csv(out / f'Table9_T0_280_Retry_{mode}_Rounds_q{q:.1f}.csv',
                     data['round_metrics'])
            result = summarize(data, round_summary, analysis, mode, q, schedule)
            print(f"  {result['Status']}: completed={result['Completed Requests']}, "
                  f"throughput={result['Throughput (tx/1000ms)']:.1f}, "
                  f"max monetary deviation={result['Max Monetary Deviation']}", flush=True)
        finally:
            del tx, ids, matrix
            if data is not None:
                del data
            gc.collect()
        summary = [x for x in summary if pair_key(x) != target]
        summary.append(result)
        order = {'Barrier-NoTimeout':0,'Barrier-WithTimeout':1}
        summary.sort(key=lambda r:(order[r['Mode']], float(r['q']) if str(r['q']) else 0))
        save_csv(summary_path, summary)
        gc.collect()
    print(f'Finished. Summary: {summary_path}', flush=True)

if __name__ == '__main__':
    main()
