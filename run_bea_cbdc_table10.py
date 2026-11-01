#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 10: seven single-run CBDC settlement comparisons with long AC failures.

FINAL EXPERIMENT SCENARIO (1,000,000-ms horizon):
    1,000 ACs; exactly 500 (50%) selected to fail ONCE each.
    Each selected AC starts failure uniformly in reference rounds 100..500
    and fails for a uniformly selected 100..400 reference rounds, 1000ms each.
    The fixed schedule and synthetic transaction workload are regenerated
    identically for all seven mechanisms using a common seed 42.

Seven runs in order: Time-Based Cutoff; Barrier No Timeout q=.7/.8/.9;
Barrier With Timeout q=.7/.8/.9. Timeout (T0,T2) pairs in ms:
    q=.7: (10,443), q=.8: (20,510), q=.9: (100,616).

No-timeout barrier waits for AC RECOVERY (it does NOT falsely terminate when
quorum is temporarily unavailable). If an unresolved stage remains past the
common measurement horizon, its status is BLOCKED_AT_HORIZON, not deadlocked.

Requires these files in the same folder:
    bea_cbdc_basic_barrier_table9_no_timeout.py    (unchanged Table 9 engine)
    run_bea_cbdc_table9_barrier_no_timeout.py      (unchanged Table 9 analyzer)
    bea_cbdc_table10_barrier.py                    (new Table 10 engine)

Commands:
    python3 run_bea_cbdc_table10.py --list
    python3 run_bea_cbdc_table10.py --smoke-test
    python3 run_bea_cbdc_table10.py
    python3 run_bea_cbdc_table10.py --mode barrier --q 0.9
    python3 run_bea_cbdc_table10.py --mode cutoff
    python3 run_bea_cbdc_table10.py --reset

Run outputs under table10_long_failure/ (smoke under table10_long_failure_smoke/).
Each configuration is run ONCE. This is a scenario study, not a confidence-
interval experiment. Outputs are synthetic; each run executes sequentially.
"""

import argparse
import contextlib
import csv
import gc
import hashlib
import importlib.util
import json
import os
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
        raise FileNotFoundError(f'{filename} missing. Place all four files together in {HERE}')
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


def failure_schedule(cfg):
    """50% selected, independent single failure per AC, shared by 7 runs.

    Random draw of AC IDs/starts/durations is intentionally independent of
    transaction and network RNG streams to guarantee the same outages.
    """
    rng = random.Random(SEED)
    n_failed = int(round(cfg.N_AC * cfg.P_Fail_AC))
    selected = rng.sample(range(cfg.N_AC), n_failed)
    failures = {}
    for ac_id in selected:
        start = rng.randint(cfg.R_Fail_Start, cfg.R_Fail_End)
        duration = rng.randint(cfg.Min_Fail_Duration, cfg.Max_Fail_Duration)
        end = min(start + duration - 1, cfg.N_Round - 1)
        failures[ac_id] = [(start, end)]
    return dict(sorted(failures.items()))


def setup_cfg(base, smoke=False):
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
    cfg.R_Fail_End = 500
    cfg.Min_Fail_Duration = 100
    cfg.Max_Fail_Duration = 400
    cfg.log_level = 0
    if smoke:
        cfg.N_AC = 40
        cfg.N_User = 4000
        cfg.N_Round = 80
        cfg.lambda_tx = 0.25
        cfg.N_Tx_per_AC_block = 400
        cfg.R_Fail_Start = 10
        cfg.R_Fail_End = 40
        cfg.Min_Fail_Duration = 10
        cfg.Max_Fail_Duration = 30
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


def run_cutoff(base, cfg, tx, ids, matrix, output, schedule):
    """Use the original unchanged cutoff engine; capture its large NPZ in RAM."""
    backlog = np.zeros((cfg.N_Round-20, cfg.N_AC), dtype=np.int32)
    sum_balances = np.zeros((cfg.N_Round, cfg.N_AC), dtype=np.int64)
    sum_pending = np.zeros_like(sum_balances)
    captured = {}
    saver = np.savez_compressed
    original_generator = base.generate_failure_schedule
    old_cwd = Path.cwd()

    def capture_npz(_path, **kwargs):
        captured.update(kwargs)

    log_path = output / 'Table10_Cutoff_Console.log'
    try:
        base.generate_failure_schedule = lambda unused: schedule
        np.savez_compressed = capture_npz
        os.chdir(output)
        with log_path.open('w', encoding='utf-8') as log:
            with contextlib.redirect_stdout(log):
                base.run_simulation(cfg, tx, ids, matrix, backlog,
                                    sum_balances, sum_pending)
    finally:
        os.chdir(old_cwd)
        base.generate_failure_schedule = original_generator
        np.savez_compressed = saver

    if captured.get('failure_schedule') != schedule:
        raise AssertionError('Cutoff run used a different failure schedule')
    online = np.asarray(captured['num_non_failed_ACs'])
    rep = np.asarray(captured['report_success'])
    ready = np.asarray(captured['readiness_success'])
    totals = sum_balances.sum(axis=1)+sum_pending.sum(axis=1)
    pending_sums = sum_pending.sum(axis=1)
    rows = []
    for n in range(10, cfg.N_Round-10):
        ix = n-10
        num_online = int(online[n])
        online_backlog = int(np.maximum(backlog[ix], 0).sum())
        rows.append({
            'EC_Round': n,
            'Round_Open_ms': n*cfg.Delta_R,
            'Next_Round_Open_ms': (n+1)*cfg.Delta_R,
            'Round_Duration_ms': cfg.Delta_R,
            'Unavailable_ACs': cfg.N_AC-num_online,
            'Report_Success': float(rep[ix]),
            'Readiness_Success_Given_Report': float(ready[ix]),
            'Completed_Tx': int(captured['completed_tx_per_round'][ix]),
            'Total_Backlog': online_backlog,
            'Backlog_per_Active_AC': online_backlog/num_online if num_online else 0.0,
            'Pending_CBDC': int(pending_sums[n]),
            'Total_CBDC': int(totals[n]),
        })
    save_csv(output/'Table10_Cutoff_Rounds.csv', rows)
    avg = lambda col: float(np.mean([r[col] for r in rows]))
    summary = {
        'EC Round Duration Mean (ms)': float(cfg.Delta_R),
        'T0 Wait Mean (ms)': 0.0,
        'T2 Wait Mean (ms)': float(cfg.D_ready),
        'Total Backlog Mean': avg('Total_Backlog'),
        'Backlog/Active AC Mean': avg('Backlog_per_Active_AC'),
        'Pending CBDC Mean': avg('Pending_CBDC'),
        'Report Success Mean': avg('Report_Success'),
        'Readiness Success Given Report Mean': avg('Readiness_Success_Given_Report'),
        'Unavailable AC Mean': avg('Unavailable_ACs'),
        'Unavailable AC Max': max(r['Unavailable_ACs'] for r in rows),
        'Number of EC Rounds': cfg.N_Round,
        'Simulation End (ms)': cfg.N_Round*cfg.Delta_R,
        'Max Monetary Deviation': int(np.max(np.abs(totals-totals[0]))),
    }
    data = {'cfg': vars(cfg).copy(), 'Total_Tx': tx,
            'failure_schedule': schedule,
            'Traffic_Horizon_ms': cfg.N_Round*cfg.Delta_R,
            'Status': 'COMPLETED', 'Stop_Reason': ''}
    return data, summary


def summarize(data, round_metrics, analysis, mode, q, schedule):
    tx = analysis.analyze_transactions(data)
    result = {
        'Mode': {'cutoff':'Time-Based Cutoff',
                 'barrier':'Barrier-NoTimeout',
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
    if mode != 'cutoff':
        result['T0 Timeout Count'] = sum(r['T0_Timeout_Triggered']
                                        for r in data['round_metrics'])
        result['T2 Timeout Count'] = sum(r['T2_Timeout_Triggered']
                                        for r in data['round_metrics'])
        result['Max T0 Wait (ms)'] = max((r['Report_Wait_ms']
                                         for r in data['round_metrics']), default='')
        result['Max T2 Wait (ms)'] = max((r['Readiness_Wait_ms']
                                         for r in data['round_metrics']), default='')
        result['Pending Barrier Start (ms)'] = data['Pending_Barrier_Start_ms']
        result['Next Quorum Time (ms)'] = data['Pending_Barrier_Next_Quorum_ms']
        if mode == 'timeout':
            result['T0 Timeout (ms)'], result['T2 Timeout (ms)'] = (
                __import__('bea_cbdc_table10_barrier').TIMEOUTS[q])
    if result['Max Monetary Deviation'] != 0:
        raise AssertionError('CBDC conservation invariant was violated')
    return result


def pair_key(item):
    return (str(item['Mode']), str(item.get('q', '')))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=('all','cutoff','barrier','timeout'),
                        default='all')
    parser.add_argument('--q', type=float, choices=THRESHOLDS)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--reset', action='store_true',
                        help='Repeat selected runs, replacing their existing results')
    parser.add_argument('--progress-every', type=int, default=100)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.q is not None and args.mode not in ('barrier','timeout'):
        parser.error('--q can only be used with --mode barrier/timeout')

    engine = load_module('bea_cbdc_table10_barrier', 'bea_cbdc_table10_barrier.py')
    base = engine.base
    analysis = load_module('table10_analysis', 'run_bea_cbdc_table9_barrier_no_timeout.py')
    cfg = setup_cfg(base, smoke=args.smoke_test)
    schedule = failure_schedule(cfg)
    concurrent = np.zeros(cfg.N_Round, dtype=np.int32)
    for one in schedule.values():
        a,b = one[0]
        concurrent[a:b+1] += 1
    max_count = int(concurrent.max())
    max_round = int(np.argmax(concurrent))
    mean_count = float(concurrent.mean())
    print(f'Table 10: {cfg.N_AC} ACs, {len(schedule)} failed once; '
          f'failure starts {cfg.R_Fail_Start}-{cfg.R_Fail_End} sec; '
          f'duration {cfg.Min_Fail_Duration}-{cfg.Max_Fail_Duration} sec')
    print(f'  Mean concurrent failed ACs: {mean_count:.2f}; '
          f'peak: {max_count} (reference second {max_round})')
    jobs = [('cutoff', None)] + [(mode,q) for mode in ('barrier','timeout')
                                for q in THRESHOLDS]
    if args.mode != 'all':
        jobs = [(m,q) for m,q in jobs if m == args.mode and
                (args.q is None or q == args.q)]
    print('  Selected runs: '+', '.join(m+(f' q={q}' if q is not None else '')
                                       for m,q in jobs))
    if args.list:
        return

    out = HERE/('table10_long_failure_smoke' if args.smoke_test
               else 'table10_long_failure')
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
        'experiment': 'Table 10 long independent AC failure',
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
    }
    meta_path = out/'Table10_Scenario.json'
    same_scenario = True
    if meta_path.exists():
        prev = json.loads(meta_path.read_text(encoding='utf-8'))
        same_scenario = prev == metadata
        if not same_scenario and not args.reset:
            raise RuntimeError('Output directory contains a different scenario. '
                               'Move it aside or run --reset.')
    meta_path.write_text(json.dumps(metadata, indent=2)+'\n',encoding='utf-8')
    save_csv(out/'Table10_Failure_Schedule.csv', schedule_lines)
    save_csv(out/'Table10_Concurrent_Failures.csv', [
        {'Reference_Second':i, 'Concurrent_Failed_ACs':int(n)}
        for i,n in enumerate(concurrent)])
    summary_path = out/'Table10_All_7.csv'
    summary = []
    if summary_path.exists() and same_scenario:
        with summary_path.open(newline='',encoding='utf-8') as f:
            summary = list(csv.DictReader(f))

    for mode,q in jobs:
        label = {'cutoff':'Time-Based Cutoff','barrier':'Barrier-NoTimeout',
                 'timeout':'Barrier-WithTimeout'}[mode]
        target = (label, '' if q is None else str(q))
        if not args.reset and any(pair_key(x)==target and x.get('Status')
                                  in ('COMPLETED','OBSERVATION_END','BLOCKED_AT_HORIZON')
                                  for x in summary):
            print(f'  Already recorded: {label} q={q}. Skipping.')
            continue
        run_cfg = setup_cfg(base, smoke=args.smoke_test)
        if q is not None:
            run_cfg.barrier_threshold = q
        print(f'Running {label} q={q}; one run, seed {SEED} ...', flush=True)
        tx, ids, matrix = generate_transactions(base, run_cfg)
        data = None
        try:
            if mode == 'cutoff':
                data, round_summary = run_cutoff(base,run_cfg,tx,ids,matrix,out,schedule)
            else:
                data = engine.run_barrier_table10(
                    run_cfg,tx,ids,matrix, failure_schedule=schedule,
                    with_timeout=(mode=='timeout'),
                    progress_every=args.progress_every)
                round_summary = analysis.analyze_rounds(data)
                save_csv(out/f'Table10_{mode}_Rounds_q{q:.1f}.csv',
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
        order = {'Time-Based Cutoff':0,'Barrier-NoTimeout':1,'Barrier-WithTimeout':2}
        summary.sort(key=lambda r:(order[r['Mode']], float(r['q']) if str(r['q']) else 0))
        save_csv(summary_path, summary)
        gc.collect()
    print(f'Finished. Summary: {summary_path}', flush=True)

if __name__ == '__main__':
    main()
