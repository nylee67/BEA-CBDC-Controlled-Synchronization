#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 10 barrier engine: recovery-aware, time-based AC failures.

This module wraps the original Table 9 barrier engine for the shared CBDC
state/transaction helpers but implements a recovery-aware stage-1 and stage-2
barrier. An unbounded barrier waits for offline ACs to recover and report;
no artificial timeout is applied. Timed barriers use the fixed stage-specific
T0/T2 timeouts from Table 9.

Failure intervals use integer 1000-ms reference rounds, inclusive of their
first and last periods. Both barrier variants observe exactly the same
externally supplied failure schedule, fixed in physical time.
"""
import importlib.util
import math
from pathlib import Path
import random
import sys

import numpy as np

SOURCE = Path(__file__).with_name('bea_cbdc_basic_barrier_table9_no_timeout.py')
_spec = importlib.util.spec_from_file_location('table10_reference_engine', SOURCE)
if not SOURCE.exists():
    raise FileNotFoundError(f'Missing reference engine: {SOURCE}')
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

TIMEOUTS = {0.7: (10, 443), 0.8: (20, 510), 0.9: (100, 616)}


def failed_at(ac, timestamp_ms, delta_r):
    """Whether an AC is unavailable at this absolute simulated timestamp."""
    for start, end in ac.failure_schedule:
        if start * delta_r <= timestamp_ms < (end + 1) * delta_r:
            return True
    return False


def next_online(ac, timestamp_ms, delta_r):
    """Earliest timestamp at/after t when this AC can act again."""
    t = int(timestamp_ms)
    for start, end in sorted(ac.failure_schedule):
        lo, hi = start * delta_r, (end + 1) * delta_r
        if lo <= t < hi:
            t = hi
    return t


def after_reporting(ac, nominal_t0, round_open, cfg, comm_delay):
    """Return a plausible local-cutoff time and earliest received report.

    If AC is failed at EC round opening, a fresh report is not available
    until recovery. Otherwise preserve the pre-existing independent local
    timing, unless its nominal local event occurs during an outage.
    """
    t0 = int(nominal_t0)
    if failed_at(ac, round_open, cfg.Delta_R):
        t0 = max(t0, next_online(ac, round_open, cfg.Delta_R))
    t0 = next_online(ac, t0, cfg.Delta_R)
    t1 = t0 + cfg.d_row + comm_delay
    # A report that would be delivered in the outage cannot count until
    # recovery. Reprepare the report with the same sampled delay.
    while failed_at(ac, t1, cfg.Delta_R):
        t0 = next_online(ac, t1, cfg.Delta_R)
        t1 = t0 + cfg.d_row + comm_delay
    return int(t0), int(t1)


def run_barrier_table10(cfg, transactions, ids_per_ac, matrix, *,
                        failure_schedule, with_timeout, progress_every=100):
    if cfg.N_User % cfg.N_AC:
        raise ValueError('N_User must divide N_AC exactly.')
    if cfg.barrier_threshold not in TIMEOUTS:
        raise ValueError(f'Unexpected barrier threshold: {cfg.barrier_threshold}')
    if transactions.shape[1] != 5:
        raise ValueError('Transactions should have 5 columns')

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    q = cfg.barrier_threshold
    n_ac = cfg.N_AC
    n_user_per_ac = cfg.N_User // n_ac
    horizon = cfg.N_Round * cfg.Delta_R
    timeouts = TIMEOUTS[q] if with_timeout else (None, None)

    acs = base.initialize_access_chains(cfg)
    for ac in acs:
        ac.failure_schedule = list(failure_schedule.get(ac.ac_id, ()))
    req_times = [transactions[ids, 3] for ids in ids_per_ac]

    round_open = 0
    rounds = []
    ec_round = 0
    max_ec_rounds = max(100, cfg.N_Round * 10)
    status = 'COMPLETED'
    stop_reason = ''
    pending_barrier_start = None
    next_quorum_time = None
    initial_total_cbdc = sum(int(a.balances.sum()) for a in acs)

    while round_open < horizon:
        if ec_round >= max_ec_rounds:
            raise RuntimeError('Safety bound reached: unexpectedly many EC rounds')

        # Generate potential report arrivals but DO NOT debit future-dated
        # transactions or advance any local state before the barrier closes.
        candidates = []
        online_on_open = sum(not failed_at(a, round_open, cfg.Delta_R)
                             for a in acs)
        for ac in acs:
            nominal_t0 = ac.epsilon if ec_round == 0 else ac.next_start
            # Keep a single communication draw per AC and local EC round.
            delay = base.generate_communication_delay(cfg)
            local_cutoff, report_arrival = after_reporting(
                ac, nominal_t0, round_open, cfg, delay)
            candidates.append((report_arrival, ac.ac_id, local_cutoff))
        candidates.sort()
        target_t0 = math.ceil(q * n_ac)
        quorum_t0 = max(round_open, candidates[target_t0-1][0])
        if with_timeout:
            T0 = min(quorum_t0, round_open + timeouts[0])
        else:
            T0 = quorum_t0

        if T0 >= horizon and not with_timeout:
            # Do not claim a completed EC round when the first-stage quorum
            # arrives only after the common physical-time observation horizon.
            still_online = sum(not failed_at(ac, horizon - 1, cfg.Delta_R)
                               for ac in acs)
            status = ('BLOCKED_AT_HORIZON' if still_online < target_t0
                      else 'OBSERVATION_END')
            stop_reason = (f'T0 quorum not reached by {horizon} ms: '
                           f'EC round {ec_round}, quorum earliest at {T0} ms; '
                           f'online at horizon = {still_online}')
            pending_barrier_start = int(round_open)
            next_quorum_time = int(T0)
            break

        T1 = T0 + cfg.D_matrix
        report_participants = []
        for arrival, ac_id, t0 in candidates:
            ac = acs[ac_id]
            ac.Flag_Report = arrival <= T0
            ac.Flag_Confirm = False
            # Before T0 is reached, no deposits, debits or local state
            # changes are applied for an AC not admitted to this round.
            if not ac.Flag_Report:
                continue
            ac.t_0 = int(t0)
            ac.t_1 = int(arrival)
            ac.t_2 = T1 + base.generate_communication_delay(cfg)
            ids = ids_per_ac[ac_id]
            requested = req_times[ac_id]
            left = int(np.searchsorted(requested, ac.prev_start, 'left'))
            right = int(np.searchsorted(requested, ac.t_0, 'left'))
            if right < left:
                raise AssertionError('An AC local transaction cursor regressed')
            new_ids = ids[left:right]
            for tx_id in new_ids:
                sender = int(transactions[tx_id, 0])
                value = int(transactions[tx_id, 2])
                ac.balances[sender % n_user_per_ac] -= value
                ac.pending_balance += value
            ac.outflow_queue.extend(new_ids.tolist())
            capacity = cfg.N_Tx_per_AC_block - len(ac.current_request_collection)
            if capacity > 0:
                count = min(capacity, len(ac.outflow_queue))
                ac.current_request_collection.extend(ac.outflow_queue[:count])
                del ac.outflow_queue[:count]
            report_participants.append(ac)

        matrix.fill(0)
        for ac in acs:
            if not ac.Flag_Report:
                matrix[ac.ac_id, :] = -1
                matrix[:, ac.ac_id] = -1
        for ac in report_participants:
            for tx_id in ac.current_request_collection:
                dst_ac = int(transactions[tx_id, 1]) // n_user_per_ac
                if matrix[ac.ac_id, dst_ac] >= 0:
                    matrix[ac.ac_id, dst_ac] += int(transactions[tx_id, 2])

        # Readiness messages may also be delayed until failure recovery.
        candidates_ready = []
        for ac in report_participants:
            t3 = ac.t_2 + cfg.d_check + base.generate_communication_delay(cfg)
            # An AC failed while preparing/sending readiness cannot report
            # until recovered. Resumption adds d_check after recovery.
            while failed_at(ac, t3, cfg.Delta_R):
                t3 = next_online(ac, t3, cfg.Delta_R) + cfg.d_check
            ac.t_3 = int(t3)
            candidates_ready.append((int(t3), ac.ac_id))
        candidates_ready.sort()
        target_t2 = math.ceil(q * len(report_participants))
        if not target_t2:
            quorum_t2 = T1
        else:
            quorum_t2 = max(T1, candidates_ready[target_t2-1][0])
        if with_timeout:
            T2 = min(quorum_t2, T1 + timeouts[1])
        else:
            T2 = quorum_t2

        if T2 >= horizon and not with_timeout:
            # The first stage has completed; this is a right-censored EC
            # round. Record it but do not finalize before the horizon.
            # Account debits are balanced by pending, preserving CBDC sum.
            still_online_ready = sum(
                not failed_at(ac, horizon - 1, cfg.Delta_R)
                for ac in report_participants)
            status = ('BLOCKED_AT_HORIZON' if still_online_ready < target_t2
                      else 'OBSERVATION_END')
            stop_reason = (f'T2 readiness quorum not reached by {horizon} ms: '
                           f'EC round {ec_round}, earliest at {T2} ms; '
                           f'available readiness participants at horizon = '
                           f'{still_online_ready}')
            pending_barrier_start = int(T1)
            next_quorum_time = int(T2)
            break

        T3 = T2 + cfg.D_participant
        T4 = T3 + cfg.D_finalize
        readiness_participants = []
        for ac in report_participants:
            ac.Flag_Confirm = ac.t_3 <= T2
            ac.t_4 = T3 + base.generate_note_delay(cfg)
            if ac.Flag_Confirm:
                readiness_participants.append(ac)
            else:
                ac.prev_start = ac.t_0
                ac.next_start = ac.t_4

        for ac in acs:
            if not (ac.Flag_Report and ac.Flag_Confirm):
                matrix[ac.ac_id, :] = -1
                matrix[:, ac.ac_id] = -1
        valid = matrix != -1
        missing_subset = np.random.random(matrix.shape) < cfg.P_fail_InterAC
        matrix[valid & missing_subset] = -1

        completed = 0
        for ac in readiness_participants:
            ac.t_5 = ac.t_4 + cfg.d_finalize
            ac.next_start = ac.t_5 + cfg.d_chaining
            ac.prev_start = ac.t_0
            unresolved = []
            sum_settled = 0
            for tx_id in ac.current_request_collection:
                dst_user = int(transactions[tx_id, 1])
                dst_ac = dst_user // n_user_per_ac
                if matrix[ac.ac_id, dst_ac] > 0:
                    amount = int(transactions[tx_id, 2])
                    acs[dst_ac].balances[dst_user % n_user_per_ac] += amount
                    sum_settled += amount
                    acs[dst_ac].inflow_queue.append(tx_id)
                    transactions[tx_id, 4] = ac.t_5
                    completed += 1
                else:
                    unresolved.append(tx_id)
            ac.current_request_collection = unresolved
            ac.pending_balance -= sum_settled
            ac.local_round += 1
            ac.ec_round.append(ec_round)
            ac.start_ac_round.append(ac.t_0)

        # Non-participating ACs keep prev_start unchanged, so requests are
        # not lost when they rejoin after recovery or a missed report.
        for ac in acs:
            if not ac.Flag_Report:
                ac.next_start = max(ac.next_start, T1)

        next_round_open = T4 + cfg.D_chaining
        if next_round_open <= round_open:
            raise RuntimeError('The EC simulation clock did not advance')
        total_balance = sum(int(ac.balances.sum()) for ac in acs)
        total_pending = sum(int(ac.pending_balance) for ac in acs)
        deviation = total_balance + total_pending - initial_total_cbdc
        if deviation != 0:
            raise AssertionError('CBDC amount not conserved')
        total_backlog_all = sum(len(ac.outflow_queue) + len(ac.current_request_collection)
                                for ac in acs)
        # Match Table 6's online-AC backlog convention. Excluded AC queues
        # are separately counted to make apparent any outage-related backlog.
        total_backlog = sum(len(ac.outflow_queue) + len(ac.current_request_collection)
                            for ac in acs if not failed_at(ac, round_open, cfg.Delta_R))
        online = online_on_open
        t0_received = sum(arrival <= T0 for arrival, _, _ in candidates)
        t2_received = sum(arrival <= T2 for arrival, _ in candidates_ready)
        rounds.append({
            'EC_Round': ec_round,
            'Round_Open_ms': round_open,
            'T0_ms': T0, 'T1_ms': T1, 'T2_ms': T2,
            'T3_ms': T3, 'T4_ms': T4,
            'Next_Round_Open_ms': next_round_open,
            'Round_Duration_ms': next_round_open-round_open,
            'Report_Wait_ms': T0-round_open,
            'Readiness_Wait_ms': T2-T1,
            'Unavailable_ACs': n_ac-online,
            'Online_ACs_at_Open': online,
            'T0_Quorum_Met': int(t0_received >= target_t0),
            'T2_Quorum_Met': int(t2_received >= target_t2) if target_t2 else 0,
            'T0_Timeout_Triggered': int(with_timeout and t0_received < target_t0),
            'T2_Timeout_Triggered': int(with_timeout and target_t2 and t2_received < target_t2),
            'T0_Target_Reports': target_t0,
            'T0_Reports_Received': t0_received,
            'T2_Target_Reports': target_t2,
            'T2_Reports_Received': t2_received,
            'T0_Timeout_ms': timeouts[0] if with_timeout else '',
            'T2_Timeout_ms': timeouts[1] if with_timeout else '',
            'Report_Success': len(report_participants)/n_ac,
            'Readiness_Success_Given_Report': (
                len(readiness_participants)/len(report_participants)
                if report_participants else 0.0),
            'Completed_Tx': completed,
            'Total_Backlog': total_backlog,
            'Total_Backlog_All_ACs': total_backlog_all,
            'Backlog_per_Active_AC': total_backlog/online if online else 0.0,
            'Pending_CBDC': total_pending,
            'Total_CBDC': total_balance+total_pending,
        })
        ec_round += 1
        round_open = next_round_open
        if progress_every and ec_round % progress_every == 0:
            print(f'  {ec_round} EC rounds completed; simulated time '
                  f'{round_open}ms; q={q}; timeout={with_timeout}', flush=True)

    return {
        'cfg': vars(cfg).copy(),
        'Total_Tx': transactions,
        'round_metrics': rounds,
        'failure_schedule': failure_schedule,
        'N_EC_Rounds': ec_round,
        'Traffic_Horizon_ms': horizon,
        'Simulation_End_ms': round_open,
        'Status': status,
        'Stop_Reason': stop_reason,
        'Pending_Barrier_Start_ms': pending_barrier_start,
        'Pending_Barrier_Next_Quorum_ms': next_quorum_time,
        'Initial_Total_CBDC': initial_total_cbdc,
    }
