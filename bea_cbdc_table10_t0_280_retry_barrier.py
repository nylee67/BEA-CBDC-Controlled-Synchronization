#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 10 barrier engine: T0-eligible-relative T2 quorum and destination-fair AC queues.

This module wraps the original Table 10 barrier engine for the shared CBDC
state/transaction helpers but implements a recovery-aware stage-1 and stage-2
barrier. T0 requires ceil(q * N_AC) reports; T2 requires ceil(q * N_T0)
readiness reports, where N_T0 is the number of T0 participants. An unbounded barrier waits for offline ACs to recover and report;
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

SOURCE = Path(__file__).with_name('bea_cbdc_table10_t0_280_retry_cutoff.py')
_spec = importlib.util.spec_from_file_location('table10_reference_engine', SOURCE)
if not SOURCE.exists():
    raise FileNotFoundError(f'Missing reference engine: {SOURCE}')
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

TIMEOUTS = {0.7: (280, 443), 0.8: (280, 510), 0.9: (280, 616)}


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


def close_t2_relative(ready_arrivals, t1_ms, q, n_t0, timeout_ms):
    """T2 closes at ceil(q*N_T0) readiness reports or its timeout.

    N_T0 counts the ACs successfully admitted in the current T0 stage,
    NOT the total AC population. T2 readiness candidates are restricted
    to these T0 participants. The same rule applies to both barrier modes.
    """
    target_t2 = math.ceil(q * n_t0)
    if target_t2 == 0:
        # The timed T0 stage may close with no participants; no T2 quorum
        # remains to wait for. This is not a T2 timeout event.
        return int(t1_ms), 0
    if len(ready_arrivals) < target_t2:
        if timeout_ms is None:
            raise RuntimeError('T2 quorum cannot be reached: missing readiness candidates')
        return int(t1_ms + timeout_ms), target_t2
    quorum_t2 = max(t1_ms, ready_arrivals[target_t2 - 1][0])
    return (int(min(quorum_t2, t1_ms + timeout_ms))
            if timeout_ms is not None else int(quorum_t2)), target_t2


def receive_failed_t0_notice(ac, T1, cfg, *, receive_delay=None):
    """T0 failure notice is actionable ONLY after receiving T1's announcement.

    The original cutoff engine uses t2 = T1 + communication delay for ACs
    which attempt reporting but miss T0. If the AC is unavailable at that
    instant, it must first recover. No pending transaction is discarded or
    settled by this operation.
    """
    if receive_delay is None:
        receive_delay = base.generate_communication_delay(cfg)
    if receive_delay < 0:
        raise ValueError('Negative notification delay')
    expected = int(T1 + receive_delay)
    ac.t_2 = next_online(ac, expected, cfg.Delta_R)
    ac.next_start = max(int(ac.next_start), int(ac.t_2))
    if ac.next_start < ac.t_2 or ac.t_2 < T1:
        raise AssertionError('Failed T0 retry before preliminary matrix notice')
    return int(ac.t_2)


def run_barrier_table10(cfg, transactions, ids_per_ac, matrix, *,
                        failure_schedule, with_timeout, progress_every=100,
                        audit_retries=False):
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
    retry_audit = {
        'Attempted_T0_Report_Failures': 0,
        'Deferred_Before_T0': 0,
        'Missed_Online_At_Open': 0,
        'Preliminary_Notice_Receipts': 0,
        'Retry_Timing_Violations': 0,
        'Max_Notice_Delay_ms': 0,
        'Max_Recovery_Notice_Delay_ms': 0,
    }
    retry_trace = [] if audit_retries else None

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
        if not with_timeout and T0 - round_open >= 5 * cfg.Delta_R:
            print(f'  [Barrier] EC round {ec_round}: T0 needs '
                  f'{T0 - round_open:,} ms of simulated waiting '
                  f'(clock {round_open:,} -> {T0:,} ms)', flush=True)

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
            # Exactly the same destination-fair, non-clairvoyant batching
            # rule as the fixed-cutoff engine. All unresolved requests are
            # returned to these pools after settlement.
            ac.queue_policy.push_many(new_ids, transactions, n_user_per_ac)
            ac.ingested_count += len(new_ids)
            if ac.current_request_collection:
                raise AssertionError('Staged collection was not returned')
            ac.current_request_collection = ac.queue_policy.take(
                cfg.N_Tx_per_AC_block)
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
        T2, target_t2 = close_t2_relative(
            candidates_ready, T1, q, len(report_participants),
            timeouts[1] if with_timeout else None)
        if not with_timeout and T2 - T1 >= 5 * cfg.Delta_R:
            print(f'  [Barrier] EC round {ec_round}: T2 needs '
                  f'{T2 - T1:,} ms of simulated waiting '
                  f'(clock {T1:,} -> {T2:,} ms)', flush=True)

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
        for ac in report_participants:
            if len(ac.current_request_collection) > cfg.N_Tx_per_AC_block:
                raise AssertionError('Local block capacity exceeded')
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
                    ac.settled_count += 1
                else:
                    unresolved.append(tx_id)
            ac.queue_policy.push_many(unresolved, transactions, n_user_per_ac)
            ac.current_request_collection = []
            ac.pending_balance -= sum_settled
            ac.local_round += 1
            ac.ec_round.append(ec_round)
            ac.start_ac_round.append(ac.t_0)

        # Reporting ACs excluded at T2 must not retain a staged block.
        for ac in report_participants:
            if not ac.Flag_Confirm and ac.current_request_collection:
                ac.queue_policy.push_many(ac.current_request_collection,
                                          transactions, n_user_per_ac)
                ac.current_request_collection = []

        # Handle ACs missing T0 exactly as the fixed-cutoff retry procedure:
        # T0 miss -> T1 matrix announcement -> t2 (actual receipt) -> retry.
        # When an AC was unavailable and did not even prepare a local report
        # before T0, leave its prior local state untouched; it can resume its
        # pending request after recovery, just as the cutoff engine does.
        attempted_failures_this_round = 0
        deferred_failures_this_round = 0
        max_notice_delay_this_round = 0
        for arrival, ac_id, local_cutoff in candidates:
            ac = acs[ac_id]
            if ac.Flag_Report:
                continue
            if local_cutoff > T0 and failed_at(ac, round_open, cfg.Delta_R):
                # Like cutoff, ACs which were offline for the start of the
                # EC round do not stage a report and preserve pending state.
                # They will resume their earlier local request on recovery.
                deferred_failures_this_round += 1
                retry_audit['Deferred_Before_T0'] += 1
                continue
            # Any online-at-open AC excluded from T0 must learn that it was
            # excluded before retrying (same rule as cutoff's Flag_Report
            # failure branch). Also applies to offline-on-open ACs which
            # recovered in time to prepare a local report by T0.
            if not failed_at(ac, round_open, cfg.Delta_R):
                retry_audit['Missed_Online_At_Open'] += 1
            old_next_start = int(ac.next_start)
            t2_received = receive_failed_t0_notice(ac, T1, cfg)
            if t2_received < T1 or ac.next_start < t2_received:
                retry_audit['Retry_Timing_Violations'] += 1
                raise AssertionError('T0 retry began before notice receipt')
            delay = t2_received - T1
            attempted_failures_this_round += 1
            retry_audit['Attempted_T0_Report_Failures'] += 1
            retry_audit['Preliminary_Notice_Receipts'] += 1
            retry_audit['Max_Notice_Delay_ms'] = max(
                retry_audit['Max_Notice_Delay_ms'], delay)
            if delay > cfg.Delta_R:
                retry_audit['Max_Recovery_Notice_Delay_ms'] = max(
                    retry_audit['Max_Recovery_Notice_Delay_ms'], delay)
            max_notice_delay_this_round = max(max_notice_delay_this_round, delay)
            if retry_trace is not None:
                retry_trace.append({
                    'EC_Round': ec_round, 'AC_ID': ac_id,
                    'Mode': 'Timeout' if with_timeout else 'NoTimeout',
                    'q': q, 'Round_Open_ms': round_open,
                    'Local_t0_ms': int(local_cutoff),
                    'Late_Report_Arrival_ms': int(arrival),
                    'EC_T0_ms': T0, 'EC_T1_ms': T1,
                    'Actual_t2_Receipt_ms': t2_received,
                    'Previous_Next_Start_ms': old_next_start,
                    'New_Next_Start_ms': int(ac.next_start),
                    'Notification_Lag_ms': int(delay),
                })

        next_round_open = T4 + cfg.D_chaining
        if next_round_open <= round_open:
            raise RuntimeError('The EC simulation clock did not advance')
        for ac in acs:
            if ac.ingested_count - ac.settled_count != base.pending_count(ac):
                raise AssertionError(
                    f'Queue conservation failure at AC {ac.ac_id}, EC round {ec_round}')
        total_balance = sum(int(ac.balances.sum()) for ac in acs)
        total_pending = sum(int(ac.pending_balance) for ac in acs)
        deviation = total_balance + total_pending - initial_total_cbdc
        if deviation != 0:
            raise AssertionError('CBDC amount not conserved')
        total_backlog_all = sum(base.pending_count(ac) for ac in acs)
        # Match Table 6's online-AC backlog convention. Excluded AC queues
        # are separately counted to make apparent any outage-related backlog.
        total_backlog = sum(base.pending_count(ac)
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
            'T2_Quorum_Basis': 'T0_PARTICIPANTS',
            'T2_Reports_Received': t2_received,
            'T0_Timeout_ms': timeouts[0] if with_timeout else '',
            'T2_Timeout_ms': timeouts[1] if with_timeout else '',
            'T0_Failed_Report_Attempts': attempted_failures_this_round,
            'T0_Not_Prepared_Before_Cutoff': deferred_failures_this_round,
            'T0_Max_Failure_Notice_Lag_ms': max_notice_delay_this_round,
            'Report_Success': len(report_participants)/n_ac,
            'Readiness_Success_Among_All_ACs': len(readiness_participants)/n_ac,
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
        'Retry_Audit': retry_audit,
        'T0_Retry_Trace': retry_trace,
    }
