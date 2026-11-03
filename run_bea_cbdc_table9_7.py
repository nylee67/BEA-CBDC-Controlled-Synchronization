#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 9: seven-way destination-fair synchronization comparison.

Reuses the published Table 9 six-barrier runner and the validated
Table 10 destination-fair cutoff engine; DOES NOT alter either engine.

The cutoff run uses the archived Table 9 failure schedule, seed 42,
and the same configuration and transaction generator as the barriers.

Fast path (only new cutoff experiment):
    python3 -u run_bea_cbdc_table9_7.py --mode cutoff

All seven (the old runner skips cached barrier results):
    python3 -u run_bea_cbdc_table9_7.py --mode all

Smoke test:
    python3 -u run_bea_cbdc_table9_7.py --smoke-test --mode cutoff

Optional: --barrier-summary PATH for the existing six-barrier CSV.
The code never overwrites the original Table 6 or barrier results.
"""

import argparse
import csv
import gc
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

import run_bea_cbdc_table9_t0_280_retry as old9
import run_bea_cbdc_table10_t0_280_retry as old10
import table9_t0_280_retry_analysis as analysis

HERE = Path(__file__).resolve().parent
THRESHOLDS = (0.7, 0.8, 0.9)
STATUS_OK = {'COMPLETED', 'OBSERVATION_END', 'BLOCKED_AT_HORIZON'}


def output_suffix(args):
    return '_stress' if args.stress_test else '_smoke' if args.smoke_test else ''


def barrier_output_dir(args):
    return HERE / ('table9_t0_280_retry_barrier_6runs' + output_suffix(args))


def seven_output_dir(args):
    return HERE / ('table9_t0_280_retry_7runs' + output_suffix(args))


def read_rows(path):
    if not path.is_file():
        return []
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def schedule_fingerprint(schedule):
    lines = [
        {'AC_ID': acid, 'Failure_Start_s': periods[0][0],
         'Failure_End_Exclusive_s': periods[0][1] + 1,
         'Failure_Duration_s': periods[0][1] - periods[0][0] + 1}
        for acid, periods in schedule.items()
    ]
    return hashlib.sha256(
        json.dumps(lines, sort_keys=True).encode('utf-8')
    ).hexdigest()


def get_barrier_source(args):
    if args.barrier_summary is not None:
        p = Path(args.barrier_summary).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f'--barrier-summary not found: {p}')
        return p
    candidates = [
        barrier_output_dir(args) / 'Table9_T0_280_Retry_Barrier_All_6.csv',
        HERE / 'Table9_T0_280_Retry_Barrier_All_6.csv',
    ]
    return next((p for p in candidates if p.is_file()), candidates[0])


def validate_barriers(rows, cfg, schedule, args):
    expected = {(label, str(q))
                for label in ('Barrier-NoTimeout', 'Barrier-WithTimeout')
                for q in THRESHOLDS}
    actual = {(r.get('Mode', ''), r.get('q', '')) for r in rows}
    if actual != expected or len(rows) != 6:
        raise ValueError('Barrier summary must contain exactly the six q=0.7/0.8/0.9 rows')
    for row in rows:
        if int(row['Seed']) != old9.SEED:
            raise ValueError('Barrier seed differs from cutoff seed 42')
        if int(row['N_AC']) != cfg.N_AC or int(row['Failed ACs']) != len(schedule):
            raise ValueError('Barrier scenario differs from cutoff scenario')
        if row['Status'] not in STATUS_OK:
            raise ValueError('Barrier row is not a completed/observed experiment')
    meta = barrier_output_dir(args) / 'Table9_T0_280_Retry_Scenario.json'
    if meta.is_file():
        m = json.loads(meta.read_text(encoding='utf-8'))
        if m.get('failure_schedule_sha256') != schedule_fingerprint(schedule):
            raise ValueError('Archived failure schedule differs from barrier summary metadata')
        if m.get('queue_policy') != 'destination-fair-round-robin-v1':
            raise ValueError('Barrier queue policy differs from destination-fair')


def save_merged(args, cfg, schedule, outfile):
    cutoff_file = outfile.parent / 'Table9_T0_280_Retry_Cutoff.csv'
    cutoff_rows = read_rows(cutoff_file)
    barrier_file = get_barrier_source(args)
    barrier_rows = read_rows(barrier_file)
    if not cutoff_rows:
        print('No cutoff result to merge yet.')
        return
    if len(cutoff_rows) != 1 or cutoff_rows[0].get('Mode') != 'Time-Based Cutoff':
        raise ValueError('Unexpected cutoff CSV contents')
    if not barrier_rows:
        print(f'Only cutoff result is available. Existing barrier CSV not found: {barrier_file}')
        print('Pass --barrier-summary PATH to merge the six archived barrier results.')
        return
    validate_barriers(barrier_rows, cfg, schedule, args)
    order = {'Time-Based Cutoff': 0, 'Barrier-NoTimeout': 1,
             'Barrier-WithTimeout': 2}
    rows = cutoff_rows + barrier_rows
    rows.sort(key=lambda r: (order[r['Mode']], float(r['q']) if str(r['q']) else 0))
    old9.save_csv(outfile, rows)
    print(f'Saved all 7 configurations: {outfile}')
    print('Table 9 row values:')
    for row in rows:
        print('  {0:20s} q={1:3s} latency={2:>12s} ms  '
              'never-failed={3:>12s} ms  failure-involved={4:>12s} ms  '
              'backlog={5:>14s}  status={6}'.format(
                  row['Mode'], row['q'] or '--',
                  str(row.get('All Completed Mean (ms)', '')),
                  str(row.get('Never-Failed AC Pair Mean (ms)', '')),
                  str(row.get('Failure-Involved Mean (ms)', '')),
                  str(row.get('Total Backlog Mean', '')), row['Status']))


def run_barriers(args):
    if args.barrier_summary is not None:
        print('Using --barrier-summary: no barrier rerun requested.')
        return
    cmd = [sys.executable, '-u', str(HERE / 'run_bea_cbdc_table9_t0_280_retry.py'),
           '--mode', 'all' if args.mode == 'all' else args.mode,
           '--progress-every', str(args.progress_every)]
    if args.q is not None:
        cmd.extend(['--q', str(args.q)])
    if args.smoke_test:
        cmd.append('--smoke-test')
    if args.stress_test:
        cmd.append('--stress-test')
    if args.reset_barriers:
        cmd.append('--reset')
    subprocess.run(cmd, cwd=HERE, check=True)


def run_cutoff(args, cfg, schedule, outfile):
    out = outfile.parent
    cutoff_file = out / 'Table9_T0_280_Retry_Cutoff.csv'
    meta_path = out / 'Table9_T0_280_Retry_Cutoff_Metadata.json'
    fingerprint = schedule_fingerprint(schedule)
    expected_metadata = {
        'experiment': 'Table 9 destination-fair time-based cutoff',
        'queue_policy': 'destination-fair-round-robin-v1',
        'failure_schedule_sha256': fingerprint,
        'failure_schedule_source': ('Table9_T0_280_Retry_Failure_Schedule_Input.csv'
                                    if not args.smoke_test else 'deterministic smoke schedule'),
        'seed': old9.SEED, 'N_AC': cfg.N_AC,
        'N_User': cfg.N_User, 'N_Round': cfg.N_Round,
        'Delta_R_ms': cfg.Delta_R, 'lambda_tx': cfg.lambda_tx,
        'P_Fail_AC': cfg.P_Fail_AC,
        'R_Fail_Start': cfg.R_Fail_Start, 'R_Fail_End': cfg.R_Fail_End,
        'Min_Fail_Duration': cfg.Min_Fail_Duration,
        'Max_Fail_Duration': cfg.Max_Fail_Duration,
        'capacity_per_local_round': cfg.N_Tx_per_AC_block,
        'cutoff_engine': 'bea_cbdc_table10_t0_280_retry_cutoff.py',
        'validation': 'one run; common Table 9 seed and fixed failure schedule',
    }
    if cutoff_file.is_file() and not args.rerun_cutoff:
        if not meta_path.is_file() or json.loads(meta_path.read_text(encoding='utf-8')) != expected_metadata:
            raise RuntimeError('Cutoff CSV exists with unmatched or missing metadata; '
                               'inspect the file or use --rerun-cutoff')
        rows = read_rows(cutoff_file)
        if len(rows) != 1 or rows[0]['Status'] not in STATUS_OK:
            raise ValueError('Incomplete saved cutoff run')
        print('Existing matching cutoff result: skipping rerun.')
        return

    base = old9.load_module('bea_cbdc_table10_t0_280_retry_cutoff',
                            'bea_cbdc_table10_t0_280_retry_cutoff.py')
    # Make config using the original Table 9 setup. The Table 9 and 10
    # transaction-generation primitives are identical in the published code.
    cfg = old9.setup_cfg(base, smoke=args.smoke_test, stress=args.stress_test)
    print('Running Time-Based Cutoff with destination-fair queues, seed 42.', flush=True)
    print('  Generating identical Table 9 synthetic input settings...', flush=True)
    tx, ids, matrix = old9.generate_transactions(base, cfg)
    print(f'  Generated {len(tx):,} requests; beginning cutoff simulation.', flush=True)
    data = None
    try:
        data, round_metrics = old10.run_cutoff(
            base, cfg, tx, ids, matrix, out, schedule,
            progress_every=args.progress_every)
        result = old10.summarize(data, round_metrics, analysis,
                                 'cutoff', None, schedule)
        if int(result['Max Monetary Deviation']) != 0:
            raise AssertionError('Nonzero monetary deviation')
        if result['Status'] not in STATUS_OK:
            raise RuntimeError(f"Unexpected cutoff status {result['Status']}")
        old9.save_csv(cutoff_file, [result])
        meta_path.write_text(json.dumps(expected_metadata, indent=2) + '\n',
                             encoding='utf-8')
        # The reused engine's helper has Table10 names; rename only its outputs.
        rename_pairs = [
            ('Table10_T0_280_Retry_Cutoff_Console.log',
             'Table9_T0_280_Retry_Cutoff_Console.log'),
            ('Table10_T0_280_Retry_Cutoff_Rounds.csv',
             'Table9_T0_280_Retry_Cutoff_Rounds.csv'),
        ]
        for source, dest in rename_pairs:
            p = out / source
            if p.exists():
                p.replace(out / dest)
        print('Saved cutoff result:', cutoff_file, flush=True)
    finally:
        del tx, ids, matrix
        if data is not None:
            del data
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=('all', 'cutoff', 'barrier', 'timeout'),
                        default='cutoff',
                        help='Default cutoff only; all also invokes the cached six-barrier runner')
    parser.add_argument('--q', type=float, choices=THRESHOLDS)
    parser.add_argument('--barrier-summary', type=str,
                        help='Path to existing six-barrier CSV when not in the default directory')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--stress-test', action='store_true')
    parser.add_argument('--rerun-cutoff', action='store_true')
    parser.add_argument('--reset-barriers', action='store_true')
    parser.add_argument('--progress-every', type=int, default=100)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.stress_test:
        args.smoke_test = True
    if args.q is not None and args.mode not in ('barrier', 'timeout'):
        parser.error('--q is only valid for --mode barrier or timeout')
    if args.barrier_summary and args.mode in ('barrier', 'timeout'):
        parser.error('--barrier-summary cannot be used when rerunning barriers')
    if args.list:
        print('Table 9: one cutoff + six barriers; same archived outage schedule.')
        print('  cutoff: destination-fair, no q')
        for m in ('barrier', 'timeout'):
            for q in THRESHOLDS:
                print(f'  {m} q={q}: destination-fair')
        print('Default execution runs only cutoff; existing barriers are reused.')
        return

    base = old9.load_module('bea_cbdc_table10_t0_280_retry_cutoff',
                            'bea_cbdc_table10_t0_280_retry_cutoff.py')
    cfg = old9.setup_cfg(base, smoke=args.smoke_test, stress=args.stress_test)
    schedule = old9.failure_schedule(cfg, smoke=args.smoke_test)
    if not args.smoke_test and len(schedule) != 500:
        raise AssertionError('Full Table 9 must have exactly 500 failed ACs')
    if not args.smoke_test:
        concurrent = np.zeros(cfg.N_Round, dtype=np.int32)
        for failures in schedule.values():
            start, end = failures[0]
            concurrent[start:end + 1] += 1
        if int(concurrent.max()) != 56:
            raise AssertionError('Archived Table 9 failure schedule did not match peak 56')
    out = seven_output_dir(args)
    out.mkdir(exist_ok=True)
    outfile = out / 'Table9_T0_280_Retry_All_7.csv'
    if args.mode in ('all', 'barrier', 'timeout'):
        run_barriers(args)
    if args.mode in ('all', 'cutoff'):
        run_cutoff(args, cfg, schedule, outfile)
    save_merged(args, cfg, schedule, outfile)


if __name__ == '__main__':
    main()
