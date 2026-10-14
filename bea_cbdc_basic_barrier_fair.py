# bea_cbdc_basic.py

# ============================================================
# A. Imports
# ============================================================

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import random
import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# B. Data Structures
# ============================================================

@dataclass
class AccessChain:
    ac_id: int

    # Local account states
    balances: np.ndarray
    pending_balance: int = 0

    # Local synchronization state
    local_round: int = 0

    # t_0 of successful local round and corrspondinh EC round 
    start_ac_round: List[int] = field(default_factory=list)
    ec_round: List[int] = field(default_factory=list)

    # Initial local timing offset
    epsilon: int = 0
    next_start: int = 0
    prev_start: int = 0

    t_0: int = 0
    t_1: int = 0
    t_2: int = 0
    t_3: int = 0
    t_4: int = 0
    t_5: int = 0

    # Success/Failure of Report/Confirm
    Flag_Report: bool = False
    Flag_Confirm: bool = False

    # Transaction queues - tx_id only
    outflow_queue: List[int] = field(default_factory=list)
    current_request_collection: List[int] = field(default_factory=list)
    inflow_queue: List[int] = field(default_factory=list)

    # Failure intervals
    failure_schedule: List[Tuple[int, int]] = field(default_factory=list)


# ============================================================
# C. Simulation Configuration
# ============================================================

@dataclass
class Config:

    # --------------------------------------------------------
    # Simulation Choice
    # --------------------------------------------------------
    Flag_Burst: bool = True 

    # --------------------------------------------------------
    # Simulation scale
    # --------------------------------------------------------

    N_Round: int = 1000

    N_AC: int = 1000                    # Simulation cases: 100, 500, 1000
    N_User: int = 100_000_000

    N_Tx_per_AC_block: int = 4000

    # --------------------------------------------------------
    # EC synchronization timing
    # --------------------------------------------------------

    Delta_R: int = 1000                 # Synchronization-round duration (ms)

    D_matrix: int = 40
    D_ready: int = 360
    D_participant: int = 280
    D_finalize: int = 40
    D_chaining: int = 280               # Sum of D_* = Delta_R

    # --------------------------------------------------------
    # AC local timing
    # --------------------------------------------------------

    epsilon_min: int = 10               # Minimum initial AC synchronization offset (ms)
    epsilon_max: int = 50               # Maximum initial AC synchronization offset (ms)

    d_row: int = 40                     # Settlement-summary preparation time (ms)
    d_check: int = 60                   # Settlement-readiness verification time (ms)
    d_note_max: int = 200               # Final-settlement recognition time (ms)
    d_finalize: int = 40                # Local-block finalization time (ms)
    d_chaining: int = 20                # Next local-block chaining time (ms)

    P_fail_InterAC: float = 1e-5        # Probability that an Inter-AC transfer subset
                                        # is unavailable in the current round

    # --------------------------------------------------------
    # EC-AC communication delay model
    # --------------------------------------------------------

    d_delay_min: float = 20.0
    d_delay_lambda: float = 1 / 80.0

    # --------------------------------------------------------
    # Transaction traffic
    # --------------------------------------------------------

    lambda_tx: float = 100.0            # Simulation cases: 10, 50, 100 requests/ms
    lambda_tx_burst: float = 2000.0     # Burst arrival rate (requests/ms)

    R_burst: int = 500                  # Burst starts at synchronization round 500
    L_burst: int = 50                   # Burst lasts for rounds 500--549

    # --------------------------------------------------------
    # AC failures
    # --------------------------------------------------------

    P_Fail_AC: float = 0.0              # Simulation cases: 0.00, 0.01, 0.05

    R_Fail_Start: int = 100             # Earliest failure-start round
    R_Fail_End: int = 800               # Latest failure-start round

    Min_Fail_Duration: int = 20         # Minimum failure duration (rounds)
    Max_Fail_Duration: int = 100        # Maximum failure duration (rounds)

    # --------------------------------------------------------
    # Monetary parameters
    # --------------------------------------------------------

    min_init_balance: int = 100_000
    max_init_balance: int = 10_000_000

    min_tx_amount: int = 1
    max_tx_amount: int = 10_000

    # --------------------------------------------------------
    # Randomness / Logging
    # --------------------------------------------------------

    seed: int = 42

    # Barrier-based synchronization comparison (no fixed cutoff / timeout)
    barrier_threshold: float = 0.70

    # Logging level
    # 0 : No logging
    # 1 : EC timing + Settlement Matrix + Round Summary
    # 2 : Level 1 + Access-chain states
    # 3 : Level 2 + Transaction details
    log_level: int = 0


# ============================================================
# D. Utility Functions
# ============================================================

def generate_communication_delay(cfg: Config) -> int:
    delay = cfg.d_delay_min + random.expovariate(cfg.d_delay_lambda)
    return int(round(delay))


def generate_note_delay(cfg: Config) -> int:
    while True:
        delay = cfg.d_delay_min + random.expovariate(cfg.d_delay_lambda)
        if delay <= cfg.d_note_max:
            return int(round(delay))

        
def generate_failure_schedule(
    cfg: Config,
) -> Dict[int, List[Tuple[int, int]]]:
    """
    Generate random failure schedules for access chains.

    Returns
    -------
    Dict[int, List[Tuple[int, int]]]

        Key
            Access-chain ID.

        Value
            List of failure intervals.

            Each tuple is

                (failure_start_round,
                 failure_end_round)

            Multiple intervals are allowed for future extensions.

    ex. {
            12: [(135, 182)],
            417: [(604, 656)],
            831: [(720, 793)]
        }
    """

    n_failed = int(round(cfg.N_AC * cfg.P_Fail_AC))

    failure_schedule: Dict[int, List[Tuple[int, int]]] = {}

    if n_failed == 0:
        return failure_schedule

    failed_ac_ids = random.sample(
        range(cfg.N_AC),
        n_failed,
    )

    for ac_id in failed_ac_ids:

        start_round = random.randint(
            cfg.R_Fail_Start,
            cfg.R_Fail_End,
        )

        duration = random.randint(
            cfg.Min_Fail_Duration,
            cfg.Max_Fail_Duration,
        )

        end_round = min(
            start_round + duration - 1,
            cfg.N_Round - 1,
        )

        failure_schedule[ac_id] = [
            (start_round, end_round)
        ]

    return failure_schedule


def initialize_access_chains(
    cfg: Config,
) -> List[AccessChain]:
    """
    Initialize all access chains.

    Each access chain is assigned:

        - local account balances
        - initial local timing offset
        - empty transaction queues
        - empty local-block history
        - empty failure schedule
    """

    ACs: List[AccessChain] = []

    # --------------------------------------------------------
    # Number of users managed by each access chain
    # --------------------------------------------------------

    N_UserAC = cfg.N_User // cfg.N_AC

    # --------------------------------------------------------
    # Initialize access chains
    # --------------------------------------------------------

    for ac_id in range(cfg.N_AC):

        # Local account balances
        balances = np.random.randint(
            cfg.min_init_balance,
            cfg.max_init_balance + 1,
            size=N_UserAC,
            dtype=np.int64,
        )

        # Initial local timing offset
        epsilon = random.randint(
            cfg.epsilon_min,
            cfg.epsilon_max,
        )

        ac = AccessChain(
            ac_id=ac_id,
            balances=balances,
            epsilon=epsilon,
        )

        ACs.append(ac)

    return ACs


def is_ac_failed(
    ac: AccessChain,
    n: int,
) -> bool:
    """
    Return True if the access chain is in a failure interval
    during synchronization round n.
    """

    for start_round, end_round in ac.failure_schedule:
        if start_round <= n <= end_round:
            return True

    return False


def initialize_request_schedule(
    cfg: Config
) -> np.ndarray:
    """
    Generate the number of transfer requests for each millisecond
    before the simulation starts.

    Normal period:
        Num_Tx_per_ms[t] ~ Poisson(lambda_tx)

    Burst period:
        Num_Tx_per_ms[t] ~ Poisson(lambda_tx_burst)

    Returns
    -------
    Num_Tx_per_ms : np.ndarray
        Number of generated transfer requests for each millisecond.
    """

    # --------------------------------------------------------
    # Allocate request schedule
    # --------------------------------------------------------

    total_time = cfg.N_Round * cfg.Delta_R

    Num_Tx_per_ms = np.empty(
        total_time,
        dtype=np.int32
    )

    # --------------------------------------------------------
    # Generate requests round by round
    # --------------------------------------------------------

    for n in range(cfg.N_Round):

        # Determine transaction arrival rate
        if (cfg.Flag_Burst and cfg.R_burst <= n < cfg.R_burst + cfg.L_burst):
            lambda_n = cfg.lambda_tx_burst
        else:
            lambda_n = cfg.lambda_tx

        # Time range of synchronization round n
        start = n * cfg.Delta_R
        end = start + cfg.Delta_R

        # Generate the number of transactions for each ms
        Num_Tx_per_ms[start:end] = np.random.poisson(
            lam=lambda_n,
            size=cfg.Delta_R
        )

    return Num_Tx_per_ms


def generate_Total_Tx(
    cfg: Config,
    Num_Tx_per_ms: np.ndarray,
    Total_Tx: np.ndarray,
) -> None:

    print("Generating Total_Tx ...")

    Num_Total_Tx = Total_Tx.shape[0]

    print(f"  Number of transactions = {Num_Total_Tx:,}")

    # --------------------------------------------------------
    # Source user
    # --------------------------------------------------------

    print("  Generating source users...")

    Total_Tx[:, 0] = np.random.randint(
        0,
        cfg.N_User,
        size=Num_Total_Tx,
        dtype=np.int32
    )

    print("    Done.")

    # --------------------------------------------------------
    # Destination user
    # --------------------------------------------------------

    print("  Generating destination users...")

    Total_Tx[:, 1] = np.random.randint(
        0,
        cfg.N_User,
        size=Num_Total_Tx,
        dtype=np.int32
    )

    print("    Done.")

    # --------------------------------------------------------
    # Prevent self-transfer
    # --------------------------------------------------------

    print("  Removing self-transfers...")

    same = Total_Tx[:, 0] == Total_Tx[:, 1]

    iteration = 0

    while np.any(same):

        iteration += 1

        Num_Same = np.count_nonzero(same)

        print(
            f"    Iteration {iteration}: "
            f"{Num_Same:,} self-transfers remaining"
        )

        Total_Tx[same, 1] = np.random.randint(
            0,
            cfg.N_User,
            size=Num_Same,
            dtype=np.int32
        )

        same = Total_Tx[:, 0] == Total_Tx[:, 1]

    print("    Done.")

    # --------------------------------------------------------
    # Transfer amount
    # --------------------------------------------------------

    print("  Generating transfer amounts...")

    Total_Tx[:, 2] = np.random.randint(
        cfg.min_tx_amount,
        cfg.max_tx_amount + 1,
        size=Num_Total_Tx,
        dtype=np.int32
    )

    print("    Done.")

    # --------------------------------------------------------
    # Requested time
    # --------------------------------------------------------

    print("  Generating requested times...")

    Total_Tx[:, 3] = np.repeat(
        np.arange(
            cfg.N_Round * cfg.Delta_R,
            dtype=np.int32
        ),
        Num_Tx_per_ms
    )

    print("    Done.")

    # --------------------------------------------------------
    # Completion time
    # --------------------------------------------------------

    print("  Initializing completion times...")

    Total_Tx[:, 4] = -1

    print("    Done.")

    print("Finished generating Total_Tx.")


def classify_Total_Tx_per_AC(
    cfg: Config,
    Total_Tx: np.ndarray,
    Tx_IDs_per_AC: List[np.ndarray],
) -> None:
    """
    Classify transaction IDs according to their source access chain.

    Tx_IDs_per_AC[i] contains the tx_id values of all transactions
    whose source account belongs to AC_i.

    The transaction data itself remains only in Total_Tx.
    """

    print("\nClassifying transactions by source Access Chain...")

    # --------------------------------------------------------
    # Number of users managed by each access chain
    # --------------------------------------------------------

    N_UserAC = cfg.N_User // cfg.N_AC

    # --------------------------------------------------------
    # Determine source AC of every transaction
    # --------------------------------------------------------

    print("  Determining source AC of each transaction...")

    src_ac = (
        Total_Tx[:, 0] // N_UserAC
    ).astype(np.int32)

    print("    Done.")

    # --------------------------------------------------------
    # Sort tx_id values by source AC
    # --------------------------------------------------------

    print("  Sorting transaction IDs...")

    sorted_tx_ids = np.argsort(
        src_ac,
        kind="stable"
    ).astype(np.int32)

    sorted_src_ac = src_ac[sorted_tx_ids]

    print("    Done.")

    # --------------------------------------------------------
    # Number of transactions generated by each AC
    # --------------------------------------------------------

    print("  Counting transactions for each AC...")

    counts = np.bincount(
        sorted_src_ac,
        minlength=cfg.N_AC
    )

    offsets = np.zeros(
        cfg.N_AC + 1,
        dtype=np.int64
    )

    offsets[1:] = np.cumsum(counts)

    print("    Done.")

    # --------------------------------------------------------
    # Create AC-specific tx_id arrays
    # --------------------------------------------------------

    print("  Creating Tx_IDs_per_AC...")

    for ac_id in range(cfg.N_AC):

        start = offsets[ac_id]
        end = offsets[ac_id + 1]

        Tx_IDs_per_AC[ac_id] = sorted_tx_ids[
            start:end
        ]

    print("    Done.")

    print(
        f"Finished classifying {Total_Tx.shape[0]:,} transactions "
        f"into {cfg.N_AC} Access Chains."
    )

    print(
        f"Average transactions per AC = "
        f"{Total_Tx.shape[0] / cfg.N_AC:,.1f}"
    )


# ============================================================
# E. Logging
# ============================================================

def log_round(
    f_log,
    cfg: Config,
    n: int,
    ACs: List[AccessChain],
    Total_Tx: np.ndarray,
    Settlement_Matrix: np.ndarray,
    valid: np.ndarray,
    failure: np.ndarray,
    T_0: int,
    T_1: int,
    T_2: int,
    T_3: int,
    T_4: int,
) -> None:

    # ========================================================
    # Level 0 : No logging
    # ========================================================

    if cfg.log_level == 0:
        return

    # ========================================================
    # Round header
    # ========================================================

    f_log.write("\n")
    f_log.write("=" * 100 + "\n")
    f_log.write(f"EC ROUND {n}\n")
    f_log.write("=" * 100 + "\n")

    # ========================================================
    # Round Summary
    # ========================================================

    outflow_amount = np.where(
        Settlement_Matrix > 0,
        Settlement_Matrix,
        0,
    ).sum(axis=1)

    inflow_amount = np.where(
        Settlement_Matrix > 0,
        Settlement_Matrix,
        0,
    ).sum(axis=0)

    total_out = int(outflow_amount.sum())
    total_in = int(inflow_amount.sum())

    num_report_fail = sum(
        not ac.Flag_Report
        for ac in ACs
    )

    num_confirm_fail = sum(
        not ac.Flag_Confirm
        for ac in ACs
    )

    num_interac_fail = int(
        np.count_nonzero(valid & failure)
    )

    f_log.write("\n[ROUND SUMMARY]\n")

    f_log.write(
        f"Report failures : {num_report_fail}\n"
    )

    f_log.write(
        f"Confirm failures: {num_confirm_fail}\n"
    )

    f_log.write(
        f"InterAC failures: {num_interac_fail}\n"
    )

    f_log.write("\n")

    f_log.write(
        f"Total Out       : {total_out}\n"
    )

    f_log.write(
        f"Total In        : {total_in}\n"
    )

    f_log.write(
        f"Difference      : {total_out - total_in}\n"
    )

    if total_out == total_in:
        f_log.write("Result          : PASS\n")
    else:
        f_log.write("Result          : FAIL\n")

    # ========================================================
    # Level 1 : EC timing + Settlement Matrix
    # ========================================================

    f_log.write("\n[EC TIMING]\n")

    f_log.write(f"T_0 = {T_0}\n")
    f_log.write(f"T_1 = {T_1}\n")
    f_log.write(f"T_2 = {T_2}\n")
    f_log.write(f"T_3 = {T_3}\n")
    f_log.write(f"T_4 = {T_4}\n")

    f_log.write("\n[SETTLEMENT MATRIX]\n")

    for row in Settlement_Matrix:
        f_log.write(
            " ".join(
                f"{int(v):10d}"
                for v in row
            )
            + "\n"
        )

    # ========================================================
    # Level 1 ends here
    # ========================================================

    if cfg.log_level == 1:
        return

    # ========================================================
    # Level 2 : Access-chain states
    # ========================================================

    for ac in ACs:

        f_log.write("\n")
        f_log.write("-" * 100 + "\n")
        f_log.write(f"[AC {ac.ac_id}]\n")
        f_log.write("-" * 100 + "\n")

        # ----------------------------------------------------
        # Synchronization state
        # ----------------------------------------------------

        f_log.write("\n[SYNCHRONIZATION]\n")

        f_log.write(
            f"local_round = {ac.local_round}\n"
        )

        f_log.write(
            f"prev_start  = {ac.prev_start}\n"
        )

        f_log.write(
            f"next_start  = {ac.next_start}\n"
        )

        f_log.write(
            f"Report      = "
            f"{'OK' if ac.Flag_Report else 'FAIL'}\n"
        )

        f_log.write(
            f"Confirm     = "
            f"{'OK' if ac.Flag_Confirm else 'FAIL'}\n"
        )

        # ----------------------------------------------------
        # Local timing
        # ----------------------------------------------------

        f_log.write("\n[LOCAL TIMING]\n")

        f_log.write(f"t_0 = {ac.t_0}\n")
        f_log.write(f"t_1 = {ac.t_1}\n")
        f_log.write(f"t_2 = {ac.t_2}\n")
        f_log.write(f"t_3 = {ac.t_3}\n")
        f_log.write(f"t_4 = {ac.t_4}\n")
        f_log.write(f"t_5 = {ac.t_5}\n")

        # ----------------------------------------------------
        # Successful local rounds
        # ----------------------------------------------------

        f_log.write("\n[LOCAL HISTORY]\n")

        if ac.local_round > 0:

            f_log.write(
                f"Last start_ac_round = "
                f"{ac.start_ac_round[-1]}\n"
            )

            f_log.write(
                f"Last ec_round       = "
                f"{ac.ec_round[-1]}\n"
            )

        else:

            f_log.write(
                "No successful local round yet.\n"
            )

        # ----------------------------------------------------
        # Queue status
        # ----------------------------------------------------

        f_log.write("\n[QUEUE STATUS]\n")

        f_log.write(
            f"outflow_queue              = "
            f"{len(ac.outflow_queue)}\n"
        )

        f_log.write(
            f"current_request_collection = "
            f"{len(ac.current_request_collection)}\n"
        )

        f_log.write(
            f"inflow_queue               = "
            f"{len(ac.inflow_queue)}\n"
        )

        # ----------------------------------------------------
        # Settlement amounts
        # ----------------------------------------------------

        f_log.write("\n[SETTLEMENT AMOUNTS]\n")

        f_log.write(
            f"Outflow amount = "
            f"{int(outflow_amount[ac.ac_id])}\n"
        )

        f_log.write(
            f"Inflow amount  = "
            f"{int(inflow_amount[ac.ac_id])}\n"
        )

        # ----------------------------------------------------
        # Account balance
        # ----------------------------------------------------

        f_log.write("\n[ACCOUNT STATE]\n")

        f_log.write(
            f"Total balance = "
            f"{int(ac.balances.sum())}\n"
        )

    # ========================================================
    # Level 2 ends here
    # ========================================================

    if cfg.log_level == 2:
        return

    # ========================================================
    # Level 3 : Transaction details
    # ========================================================

    def write_tx_list(
        title: str,
        tx_ids: List[int],
    ) -> None:

        f_log.write("\n")
        f_log.write(
            f"[{title}] count = {len(tx_ids)}\n"
        )

        if not tx_ids:
            f_log.write("Empty\n")
            return

        f_log.write(
            "tx_id      src      dst      amount"
            "    requested_time    completed_time    status\n"
        )

        f_log.write(
            "-" * 95 + "\n"
        )

        for tx_id in tx_ids:

            src = int(
                Total_Tx[tx_id, 0]
            )

            dst = int(
                Total_Tx[tx_id, 1]
            )

            amount = int(
                Total_Tx[tx_id, 2]
            )

            requested_time = int(
                Total_Tx[tx_id, 3]
            )

            completed_time = int(
                Total_Tx[tx_id, 4]
            )

            if completed_time >= 0:
                status = "DONE"
            else:
                status = "PENDING"

            f_log.write(
                f"{tx_id:8d} "
                f"{src:8d} "
                f"{dst:8d} "
                f"{amount:10d} "
                f"{requested_time:17d} "
                f"{completed_time:17d} "
                f"{status:>10s}\n"
            )

    for ac in ACs:

        f_log.write("\n")
        f_log.write("#" * 100 + "\n")
        f_log.write(
            f"[AC {ac.ac_id} TRANSACTIONS]\n"
        )
        f_log.write("#" * 100 + "\n")

        write_tx_list(
            "OUTFLOW QUEUE",
            ac.outflow_queue,
        )

        write_tx_list(
            "CURRENT REQUEST COLLECTION",
            ac.current_request_collection,
        )

        write_tx_list(
            "INFLOW QUEUE",
            ac.inflow_queue,
        )

        f_log.write("\n[LOCAL HISTORY - FULL]\n")

        f_log.write(
            f"start_ac_round = "
            f"{ac.start_ac_round}\n"
        )

        f_log.write(
            f"ec_round       = "
            f"{ac.ec_round}\n"
        )


def plot_request_schedule(
    cfg: Config, Num_Tx_per_ms: np.ndarray, 
) -> None:
    """
    Plot the number of generated transfer requests
    for each synchronization round.

    The round-level request counts are reconstructed from
    cfg.Num_Tx_per_ms.
    """

    # --------------------------------------------------------
    # Aggregate millisecond-level requests by round
    # --------------------------------------------------------

    Num_Tx_per_round = Num_Tx_per_ms.reshape(
        cfg.N_Round,
        cfg.Delta_R
    ).sum(axis=1)

    rounds = np.arange(cfg.N_Round)

    # --------------------------------------------------------
    # Plot
    # --------------------------------------------------------

    # plt.figure(figsize=(12, 4))

    # plt.plot(
    #     rounds,
    #     Num_Tx_per_round
    # )

    # plt.xlabel("Synchronization Round")
    # plt.ylabel("Number of Transfer Requests")
    # plt.title("Transaction Request Schedule")

    # plt.grid(True)
    # plt.tight_layout()
    # plt.show()


def run_simulation(
    cfg: Config,
    Total_Tx: np.ndarray,
    Tx_IDs_per_AC: List[np.ndarray],
    Settlement_Matrix: np.ndarray,
    backlog: np.ndarray,
    Sum_balance: np.ndarray,
    Sum_pending_balance: np.ndarray,
):

    """
        프로그램 구조
        for EC round:
            for each ac
                for each newly added tx to outflow 
                    Debit(ac.balances[tx's sender_id]) --> AddUp to ac.pending_balance    

                normal operation

                if ac is participant in FSM
                    for each tx in ac.current_request_collection
                        Credit(tx's dst_ac.balances[tx's receiver's id]) 
                    Subtract sum of Credit from ac.pending_balance


    """
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    N_UserAC = cfg.N_User // cfg.N_AC

    # Open log file
    f_log = open(
        "simulation.log",
        "w",
        encoding="utf-8",
    )

    completed_tx_per_round = np.zeros(cfg.N_Round - 20, dtype=np.int32)
    num_non_failed_ACs = np.zeros(cfg.N_Round, dtype=np.int32)

    AC_Report_Success_per_round = np.zeros(cfg.N_Round - 20, dtype=np.int32)
    AC_Confirm_Success_per_round = np.zeros(cfg.N_Round - 20, dtype=np.int32)

    # Initialize Access Chains
    ACs = initialize_access_chains(cfg)

    failure_schedule = generate_failure_schedule(cfg)
    for ac_id, intervals in failure_schedule.items():
        ACs[ac_id].failure_schedule = intervals

    try:
        for n in range(cfg.N_Round):

            num_added_to_outflow = 0
            num_added_to_inflow = 0

            num_completed = 0
            sum_latency = 0

            T_0 = n * cfg.Delta_R
            T_1 = T_0 + cfg.D_matrix
            T_2 = T_1 + cfg.D_ready
            T_3 = T_2 + cfg.D_participant
            T_4 = T_3 + cfg.D_finalize

            # Who fails to report: t_0 (local cutoff) t_1 (arrival of report to EC) t_2 (recognition of report)
            num_non_failed_ACs[n] = 0
            for ac in ACs:
                if is_ac_failed(ac, n):
                    ac.Flag_Report = False 
                    ac.Flag_Confirm = False
                    continue

                ac.Flag_Report = True
                num_non_failed_ACs[n] += 1

                # t_0 : local transfer-request cutoff
                if n == 0:
                    ac.prev_start = 0
                    ac.t_0 = ac.epsilon
                else:
                    ac.t_0 = ac.next_start

                # Add tx's in [ac.prev_start, ac.t_0) to ac.outflow_queue
                tx_ids = Tx_IDs_per_AC[ac.ac_id]
                requested_times = Total_Tx[tx_ids, 3]

                left = np.searchsorted(requested_times, ac.prev_start, side="left")
                right = np.searchsorted(requested_times, ac.t_0, side="left")

                new_tx_ids = tx_ids[left:right]

                # Debit sender accounts when new tx's enter outflow_queue
                for tx_id in new_tx_ids:
                    src_user = int(Total_Tx[tx_id, 0])
                    amount = int(Total_Tx[tx_id, 2])
                    src_local_id = src_user % N_UserAC
                    ac.balances[src_local_id] -= amount
                    ac.pending_balance += amount

                # Add new tx's to outflow_queue
                num_added_to_outflow += len(new_tx_ids)
                ac.outflow_queue.extend(new_tx_ids.tolist())

                # Move tx's from ac.outflow_queue to ac.current_request_collection
                # from oldest not to make len(ac.current_request_collection) exceed cfg.N_Tx_per_AC_block
                num_space = cfg.N_Tx_per_AC_block - len(ac.current_request_collection)

                if num_space > 0:
                    num_move = min(num_space, len(ac.outflow_queue))
                    ac.current_request_collection.extend(ac.outflow_queue[:num_move])
                    ac.outflow_queue = ac.outflow_queue[num_move:]

                # t_1 : settlement request arrives at CBDC EC
                d_send = generate_communication_delay(cfg)
                ac.t_1 = ac.t_0 + cfg.d_row + d_send

                # t_2 : success/failure of settlement request arrives at AC_i
                d_receive = generate_communication_delay(cfg)
                ac.t_2 = T_1 + d_receive

                if ac.t_1 >= T_0: # The settlement request cannot be included in EC round n.
                    ac.next_start = ac.t_2
                    ac.prev_start = ac.t_0
                    ac.Flag_Report = False
            
            # Preliminary Settlement Matrix 발표 
            Settlement_Matrix.fill(0)

            for ac in ACs:
                if ac.Flag_Report == False:
                    Settlement_Matrix[ac.ac_id,:] = -1
                    Settlement_Matrix[:,ac.ac_id] = -1

            if 10 <= n < cfg.N_Round - 10:
                count = 0
                for ac in ACs:
                    if ac.Flag_Report == False:
                        count += 1
                AC_Report_Success_per_round[n - 10] = cfg.N_AC - count

            for ac in ACs:
                if not ac.Flag_Report:      # 보고에 실패한 AC는 루프의 나머지 부분 생략
                    continue

                for tx_id in ac.current_request_collection:

                    dst_user = Total_Tx[tx_id, 1]
                    amount = Total_Tx[tx_id, 2]

                    dst_ac = dst_user // N_UserAC

                    # Destination AC excluded from this EC round
                    if Settlement_Matrix[ac.ac_id, dst_ac] == -1:
                        continue

                    Settlement_Matrix[ac.ac_id, dst_ac] += amount

            # Who fails to confirm: t_3 (ready confirm) t_4 (recognition of confirm)
            for ac in ACs:
                ac.Flag_Confirm = True
                if ac.Flag_Report == True:
                    # t_3 : readiness report arrives at CBDC EC
                    d_confirm = generate_communication_delay(cfg)
                    ac.t_3 = ac.t_2 + cfg.d_check + d_confirm

                    # t_4 : final settlement matrix recognized
                    d_note = generate_note_delay(cfg)
                    ac.t_4 = T_3 + d_note

                    if ac.t_3 >= T_2:
                        ac.next_start = ac.t_4
                        ac.prev_start = ac.t_0
                        ac.Flag_Confirm = False

            # Final Settlement Matrix
            for ac in ACs:
                if ac.Flag_Confirm == False:
                    Settlement_Matrix[ac.ac_id,:] = -1
                    Settlement_Matrix[:,ac.ac_id] = -1

            if 10 <= n < cfg.N_Round - 10:
                count = 0
                for ac in ACs:
                    if ac.Flag_Confirm == False and ac.Flag_Report == True:
                        count += 1
                AC_Confirm_Success_per_round[n - 10] = AC_Report_Success_per_round[n - 10] - count

            # Failure in InterAC w. cfg.P_fail_InterAC: float = 1e-6 
            valid = (Settlement_Matrix != -1)
            failure = np.random.random(Settlement_Matrix.shape) < cfg.P_fail_InterAC
            Settlement_Matrix[valid & failure] = -1

            # AC that succeeds to transfer finalize the block
            for ac in ACs:
                if ac.Flag_Report == True and ac.Flag_Confirm == True:
                    ac.t_5 = ac.t_4 + cfg.d_finalize
                    ac.next_start = ac.t_5 + cfg.d_chaining 
                    ac.prev_start = ac.t_0

                    # Settlement_Matrix[i,j] > 0 -> remove corresponding tx's from ac.current_request_collection
                    unresolved_tx_ids = []
                    sum_removed_pending_balance = 0
                    for tx_id in ac.current_request_collection:
                        dst_user = Total_Tx[tx_id, 1]
                        dst_ac = dst_user // N_UserAC

                        if Settlement_Matrix[ac.ac_id, dst_ac] > 0: # Successfully settled transaction
                            amount = int(Total_Tx[tx_id, 2])
                            dst_local_id = dst_user % N_UserAC
                            ACs[dst_ac].balances[dst_local_id] += amount
                            sum_removed_pending_balance += amount
                            ACs[dst_ac].inflow_queue.append(tx_id)
                            num_added_to_inflow += 1
                            Total_Tx[tx_id,4] = ac.t_5

                            num_completed += 1
                            sum_latency += (ac.t_5 - int(Total_Tx[tx_id, 3]))
                        else:                                       # Remains unresolved for a subsequent round
                            unresolved_tx_ids.append(tx_id)

                    ac.current_request_collection = unresolved_tx_ids
                    ac.pending_balance -= sum_removed_pending_balance

                    ac.ec_round.append(n)
                    ac.start_ac_round.append(ac.t_0)
                    ac.local_round += 1

                if 10 <= n < cfg.N_Round - 10:
                    if not is_ac_failed(ac, n):
                        r = n - 10
                        backlog[r, ac.ac_id] = len(ac.outflow_queue) + len(ac.current_request_collection)
                    else:
                        backlog[r, ac.ac_id] = -1

            for i in range(cfg.N_AC):
                Sum_balance[n, i] = ACs[i].balances.sum()
                Sum_pending_balance[n, i] = ACs[i].pending_balance

            Sum_B = 0
            Sum_P = 0
            for i in range(cfg.N_AC):
                Sum_B += Sum_balance[n, i]
                Sum_P += Sum_pending_balance[n, i]

            Total_CBDC = Sum_B + Sum_P

            # Throughput
            if 10 <= n < cfg.N_Round - 10:
                completed_tx_per_round[n - 10] = num_completed

            if 0 and n % 100 == 0:
                print(f"Round {n:4d}")  

            if 10 <= n < cfg.N_Round - 10:
                total_backlog = 0
                count = 0
                for ac in ACs:
                    if not is_ac_failed(ac, n):
                        total_backlog += (len(ac.outflow_queue) + len(ac.current_request_collection))
                        count += 1
                avg_backlog = total_backlog / count

                if num_completed > 0:
                    avg_latency = sum_latency / num_completed

                    print(
                        f"Round {n:4d} | "
                        f"Completed = {num_completed:8,d} | "
                        f"Ave. Latency = {avg_latency:8.2f} ms | " 
                        f"Ave. Backlog = {avg_backlog:8.2f} | "
                        f"Sum Balance = {Sum_B:8,d} | "
                        f"Sum Pending = {Sum_P:8,d} | "
                        f"Total CBDC = {Total_CBDC:8,d} | "
                        f"# of xFailed ACs = {num_non_failed_ACs[n]:8,d}"
                    )
                else:
                    print(
                        f"Round {n:4d} | "
                        f"Completed = 0 | "
                        f"Average Latency = N/A"
                    )


            log_round(
                f_log,
                cfg,
                n,
                ACs,
                Total_Tx,
                Settlement_Matrix,
                valid,
                failure,
                T_0,
                T_1,
                T_2,
                T_3,
                T_4,
            )

            if 0:
                # --------------------------------------------------------
                # Round progress
                # --------------------------------------------------------

                num_remaining_outflow = sum(
                    len(ac.outflow_queue)
                    for ac in ACs
                )

                print(
                    f"Round {n:4d} | "
                    f"Added->Outflow = {num_added_to_outflow:8,d} | "
                    f"Remain Outflow = {num_remaining_outflow:8,d} | "
                    f"Added->Inflow = {num_added_to_inflow:8,d}"
                )

        # Summary
        throughput_mean = np.mean(completed_tx_per_round)
        throughput_std = np.std(completed_tx_per_round)

        print(f"Average throughput : {throughput_mean:.2f}")
        print(f"Std. deviation     : {throughput_std:.2f}")

        # --------------------------------------------------------
        # Access-Chain Participation
        # --------------------------------------------------------

        report_ratio = AC_Report_Success_per_round / cfg.N_AC

        confirm_ratio = np.divide(
            AC_Confirm_Success_per_round,
            AC_Report_Success_per_round,
            out=np.zeros_like(AC_Report_Success_per_round, dtype=float),
            where=AC_Report_Success_per_round > 0,
        )

        print()
        print("Synchronization Success")
        print("-----------------------")

        print("Report Success Probability")
        print(f"  Average          : {np.mean(report_ratio):.4f}")
        print(f"  Std. deviation   : {np.std(report_ratio):.4f}")

        print("Conditional Readiness Success Probability")
        print(f"  Average          : {np.mean(confirm_ratio):.4f}")
        print(f"  Std. deviation   : {np.std(confirm_ratio):.4f}")

        np.savez_compressed(
            "Result_AC1000_NTX4000.npz",
            completed_tx_per_round = completed_tx_per_round,
            backlog = backlog,
            report_success = report_ratio,
            readiness_success = confirm_ratio,
            Total_Tx = Total_Tx,
            failure_schedule = failure_schedule,
            Sum_balance = Sum_balance,
            Sum_pending_balance = Sum_pending_balance,
            num_non_failed_ACs = num_non_failed_ACs,
            cfg = vars(cfg),
        )
    
    finally:
        f_log.close()

# ============================================================
# I. Entry point
# ============================================================

# ============================================================
# J. Barrier-based synchronization comparison
# ============================================================

def run_barrier_simulation(
    cfg: Config,
    Total_Tx: np.ndarray,
    Tx_IDs_per_AC: List[np.ndarray],
    Settlement_Matrix: np.ndarray,
    *,
    progress_every: int = 100,
) -> dict:
    """Run a two-stage, quorum-triggered EC synchronization variant.

    Stage 1: T0 is the arrival of the ceil(q*N_AC)-th settlement request.
    Stage 2: T2 is the arrival of the ceil(q*N_report)-th readiness report.
    Arrival times are actual simulated timestamps; ties are included.
    No fixed reporting deadline or timeout is applied.

    The original transaction generation, local processing, pending balance,
    settlement matrix and account-credit semantics are retained.

    Unlike the fixed-cutoff reference, the duration of an EC round varies.
    Run until the same nominal *wall-clock simulation horizon*, rather than
    forcing exactly the same number of EC rounds for every threshold. This
    permits fair comparisons of completed transactions per simulated second.

    Note: Assumes fully protocol-compliant ACs. If too many ACs are offline,
    an unbounded barrier cannot advance; this function raises an exception
    instead of fabricating a timeout or progress.
    """
    import math

    if not (0.0 < cfg.barrier_threshold <= 1.0):
        raise ValueError('barrier_threshold must be in (0, 1].')
    if cfg.N_User % cfg.N_AC:
        raise ValueError('N_User must be divisible by N_AC.')
    if Total_Tx.shape[1] < 5:
        raise ValueError('Total_Tx needs five columns.')

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    q = float(cfg.barrier_threshold)
    n_ac = cfg.N_AC
    users_per_ac = cfg.N_User // n_ac
    horizon_ms = int(cfg.N_Round * cfg.Delta_R)

    acs = initialize_access_chains(cfg)
    failure_schedules = generate_failure_schedule(cfg)
    for ac_id, intervals in failure_schedules.items():
        acs[ac_id].failure_schedule = intervals

    # Cache request times just once instead of repeatedly materializing them
    # for all ACs in every EC round. Account ID indexing remains unchanged.
    requested_by_ac = [Total_Tx[ids, 3] for ids in Tx_IDs_per_AC]
    round_open = 0
    n = 0

    rounds = []
    # An absolute bound protects against accidental algorithmic looping.
    max_rounds = max(100, cfg.N_Round * 10)

    while round_open < horizon_ms:
        if n >= max_rounds:
            raise RuntimeError('Barrier exceeded safety bound for EC rounds.')

        # --- Phase 1: each AC prepares and sends a report ---
        online = []
        for ac in acs:
            if is_ac_failed(ac, n):
                ac.Flag_Report = False
                ac.Flag_Confirm = False
                continue

            online.append(ac)
            if n == 0:
                ac.prev_start = 0
                ac.t_0 = int(ac.epsilon)
            else:
                # A new EC round cannot open before EC chaining finishes.
                ac.t_0 = int(ac.next_start)

            tx_ids = Tx_IDs_per_AC[ac.ac_id]
            request_times = requested_by_ac[ac.ac_id]
            left = int(np.searchsorted(request_times, ac.prev_start, 'left'))
            right = int(np.searchsorted(request_times, ac.t_0, 'left'))
            newly_requested = tx_ids[left:right]

            for tx_id in newly_requested:
                sender = int(Total_Tx[tx_id, 0])
                amount = int(Total_Tx[tx_id, 2])
                ac.balances[sender % users_per_ac] -= amount
                ac.pending_balance += amount

            ac.outflow_queue.extend(newly_requested.tolist())
            capacity = cfg.N_Tx_per_AC_block - len(ac.current_request_collection)
            if capacity > 0:
                moved = min(capacity, len(ac.outflow_queue))
                ac.current_request_collection.extend(ac.outflow_queue[:moved])
                del ac.outflow_queue[:moved]

            ac.t_1 = ac.t_0 + cfg.d_row + generate_communication_delay(cfg)

        target_reports = math.ceil(q * n_ac)
        if len(online) < target_reports:
            raise RuntimeError(
                f'No-timeout barrier stalled at EC round {n}: '
                f'{len(online)} online ACs, {target_reports} required.'
            )

        first_arrivals = np.fromiter((ac.t_1 for ac in online), dtype=np.int64)
        # Incoming reports may arrive before the preceding EC round has finished.
        # They remain available; do not force independent AC processing to
        # restart at the new EC round opening. A barrier cannot close before
        # the prior EC round has finished its EC chaining stage.
        T_0 = max(round_open, int(np.partition(
            first_arrivals, target_reports - 1)[target_reports - 1]
        ))
        T_1 = T_0 + cfg.D_matrix

        report_participants = []
        for ac in online:
            ac.Flag_Report = ac.t_1 <= T_0
            ac.Flag_Confirm = False
            ac.t_2 = T_1 + generate_communication_delay(cfg)
            if ac.Flag_Report:
                report_participants.append(ac)
            else:
                ac.prev_start = ac.t_0
                ac.next_start = ac.t_2

        # Preliminary settlement matrix: both outgoing and incoming ACs
        # must be included in the first barrier (including intra-AC i==j).
        Settlement_Matrix.fill(0)
        for ac in acs:
            if not ac.Flag_Report:
                Settlement_Matrix[ac.ac_id, :] = -1
                Settlement_Matrix[:, ac.ac_id] = -1

        for ac in report_participants:
            for tx_id in ac.current_request_collection:
                dst_ac = int(Total_Tx[tx_id, 1]) // users_per_ac
                if Settlement_Matrix[ac.ac_id, dst_ac] >= 0:
                    Settlement_Matrix[ac.ac_id, dst_ac] += int(Total_Tx[tx_id, 2])

        # --- Phase 2: readiness quorum (relative to first-stage participants) ---
        for ac in report_participants:
            ac.t_3 = ac.t_2 + cfg.d_check + generate_communication_delay(cfg)

        target_ready = math.ceil(q * len(report_participants))
        ready_arrivals = np.fromiter(
            (ac.t_3 for ac in report_participants), dtype=np.int64
        )
        T_2 = int(np.partition(ready_arrivals, target_ready - 1)[target_ready - 1])
        T_3 = T_2 + cfg.D_participant
        T_4 = T_3 + cfg.D_finalize

        readiness_participants = []
        for ac in report_participants:
            ac.Flag_Confirm = ac.t_3 <= T_2
            ac.t_4 = T_3 + generate_note_delay(cfg)
            if ac.Flag_Confirm:
                readiness_participants.append(ac)
            else:
                ac.prev_start = ac.t_0
                ac.next_start = ac.t_4

        # Final matrix, with the same optional transfer-subset failures
        # as the fixed-cutoff model.
        for ac in acs:
            if not (ac.Flag_Report and ac.Flag_Confirm):
                Settlement_Matrix[ac.ac_id, :] = -1
                Settlement_Matrix[:, ac.ac_id] = -1

        valid = Settlement_Matrix != -1
        failures = np.random.random(Settlement_Matrix.shape) < cfg.P_fail_InterAC
        Settlement_Matrix[valid & failures] = -1

        completed_this_round = 0
        for ac in readiness_participants:
            ac.t_5 = ac.t_4 + cfg.d_finalize
            ac.next_start = ac.t_5 + cfg.d_chaining
            ac.prev_start = ac.t_0

            unresolved = []
            sum_removed = 0
            for tx_id in ac.current_request_collection:
                dst_user = int(Total_Tx[tx_id, 1])
                dst_ac = dst_user // users_per_ac
                if Settlement_Matrix[ac.ac_id, dst_ac] > 0:
                    amount = int(Total_Tx[tx_id, 2])
                    acs[dst_ac].balances[dst_user % users_per_ac] += amount
                    sum_removed += amount
                    acs[dst_ac].inflow_queue.append(tx_id)
                    Total_Tx[tx_id, 4] = ac.t_5
                    completed_this_round += 1
                else:
                    unresolved.append(tx_id)

            ac.current_request_collection = unresolved
            ac.pending_balance -= sum_removed
            ac.ec_round.append(n)
            ac.start_ac_round.append(ac.t_0)
            ac.local_round += 1

        # Sample balances exactly as in the original model; transfers never
        # disappear on a missed synchronization attempt.
        total_available = sum(int(ac.balances.sum()) for ac in acs)
        total_pending = sum(int(ac.pending_balance) for ac in acs)
        total_backlog = sum(
            len(ac.outflow_queue) + len(ac.current_request_collection)
            for ac in acs if not is_ac_failed(ac, n)
        )
        num_online = len(online)
        next_round_open = T_4 + cfg.D_chaining
        if next_round_open <= round_open:
            raise RuntimeError('Non-increasing EC round time in barrier mode.')

        rounds.append({
            'EC_Round': n,
            'Round_Open_ms': round_open,
            'T0_ms': T_0,
            'T1_ms': T_1,
            'T2_ms': T_2,
            'T3_ms': T_3,
            'T4_ms': T_4,
            'Next_Round_Open_ms': next_round_open,
            'Round_Duration_ms': next_round_open - round_open,
            'Report_Wait_ms': T_0 - round_open,
            'Readiness_Wait_ms': T_2 - T_1,
            'Report_Success': len(report_participants) / n_ac,
            'Readiness_Success_Given_Report': (
                len(readiness_participants) / len(report_participants)
            ),
            'Completed_Tx': completed_this_round,
            'Total_Backlog': total_backlog,
            'Backlog_per_Active_AC': total_backlog / num_online,
            'Pending_CBDC': total_pending,
            'Total_CBDC': total_available + total_pending,
        })

        n += 1
        round_open = next_round_open
        if progress_every and n % progress_every == 0:
            print(
                f'Round {n:4d} | Barrier={q:.0%} | '
                f'Elapsed = {round_open:,} ms | '
                f'Completed = {completed_this_round:,} | '
                f'Backlog = {total_backlog:,}',
                flush=True,
            )

    return {
        'cfg': vars(cfg).copy(),
        'Total_Tx': Total_Tx,
        'round_metrics': rounds,
        'N_EC_Rounds': n,
        'Simulation_End_ms': round_open,
        'Traffic_Horizon_ms': horizon_ms,
    }


if __name__ == "__main__":
    cfg = Config()

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    backlog = np.zeros((cfg.N_Round - 20, cfg.N_AC), dtype=np.int32)
    Sum_balance = np.zeros((cfg.N_Round, cfg.N_AC), dtype=np.int64)          # sum of user balances in round, ac
    Sum_pending_balance = np.zeros((cfg.N_Round, cfg.N_AC), dtype=np.int64)  # sum of pending balances in round, ac

    # Simulation Choice
    cfg.Flag_Burst = False          # 여기서 버스트 여부 결정 

    # Generate transaction arrival schedule
    Num_Tx_per_ms = initialize_request_schedule(cfg)
    Num_Total_Tx = int(Num_Tx_per_ms.sum())
    plot_request_schedule(cfg, Num_Tx_per_ms)

    # Allocate transaction database
    Total_Tx = np.empty((Num_Total_Tx, 5), dtype=np.int32)
    Tx_IDs_per_AC: List[np.ndarray] = [np.empty(0, dtype=np.int32) for _ in range(cfg.N_AC)]

    # Generate individual transactions
    generate_Total_Tx(cfg, Num_Tx_per_ms, Total_Tx)
    classify_Total_Tx_per_AC(cfg, Total_Tx, Tx_IDs_per_AC)

    # Allocate settlement matrix
    Settlement_Matrix = np.full((cfg.N_AC, cfg.N_AC), -1, dtype=np.int64)

    # Run Simulation
    out = run_simulation(cfg, Total_Tx, Tx_IDs_per_AC, Settlement_Matrix, backlog, Sum_balance, Sum_pending_balance)

    print("Simulation finished.")

    # Simulation Summary
    if 1: 
        # --------------------------------------------------------
        # Request-to-Completion Latency
        # --------------------------------------------------------

        EVAL_END_ROUND = cfg.N_Round - 11
        eval_end_time = (EVAL_END_ROUND + 1) * cfg.Delta_R

        mask = (
            (Total_Tx[:, 3] < eval_end_time)
            &
            (Total_Tx[:, 4] >= 0)
        )

        latencies = (
            Total_Tx[mask, 4]
            -
            Total_Tx[mask, 3]
        )

        latency_mean = np.mean(latencies)
        latency_std = np.std(latencies)
        latency_p95 = np.percentile(latencies, 95)
        latency_p99 = np.percentile(latencies, 99)

        print()
        print("Request-to-Completion Latency")
        print("-----------------------------")
        print(f"Average latency : {latency_mean:.2f} ms")
        print(f"Std. deviation  : {latency_std:.2f} ms")
        print(f"95th percentile : {latency_p95:.2f} ms")
        print(f"99th percentile : {latency_p99:.2f} ms")

        # --------------------------------------------------------
        # Backlog per Access Chain
        # --------------------------------------------------------

        backlog_mean = np.mean(backlog)
        backlog_std = np.std(backlog)
        backlog_max = np.max(backlog)

        print()
        print("Backlog Statistics")
        print("------------------------")
        print(f"Average backlog : {backlog_mean:.2f}")
        print(f"Std. deviation  : {backlog_std:.2f}")
        print(f"Maximum backlog : {backlog_max}")

    if 0:
        Num_Requested = 0
        Num_Registered = 0
        Num_Remained = 0

        print("\n")
        print("=" * 70)
        print("SIMULATION SUMMARY")
        print("=" * 70)

        for ac_id in range(cfg.N_AC):

            tx_ids = Tx_IDs_per_AC[ac_id]

            Num_Requested_AC = len(tx_ids)

            completed_times = Total_Tx[tx_ids, 4]

            Num_Registered_AC = int(
                np.count_nonzero(completed_times >= 0)
            )

            Num_Remained_AC = int(
                np.count_nonzero(completed_times < 0)
            )

            Num_Requested += Num_Requested_AC
            Num_Registered += Num_Registered_AC
            Num_Remained += Num_Remained_AC

            print(
                f"AC {ac_id:4d} : "
                f"Requested = {Num_Requested_AC:10d}   "
                f"Registered = {Num_Registered_AC:10d}   "
                f"Remained = {Num_Remained_AC:10d}"
            )

        print("-" * 70)

        print(
            f"Total Requested  = {Num_Requested}"
        )

        print(
            f"Total Registered = {Num_Registered}"
        )

        print(
            f"Total Remained   = {Num_Remained}"
        )

        print(
            f"Check            = "
            f"{Num_Registered + Num_Remained}"
        )

        if Num_Requested == Num_Registered + Num_Remained:
            print("Transaction Check = PASS")
        else:
            print("Transaction Check = FAIL")