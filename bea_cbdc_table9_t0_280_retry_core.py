# Table 9 common simulation primitives (no Time-Based Cutoff simulation)

# ============================================================
# A. Imports
# ============================================================

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import random
from collections import deque
import numpy as np


# ============================================================
# Table 9 queue policy: destination-fair work-conserving scheduling
# ============================================================

class DestinationFairQueue:
    """FIFO within destination, round-robin between destinations.

    Scheduling does not know which destination will report or recover.
    Every local round selects at most N_Tx_per_AC_block distinct requests.
    Rejected requests are put back in their destination queues and never
    re-debited; selection never discards a request or bypasses the limit.
    """

    def __init__(self):
        self.groups = {}
        self.active = deque()
        self.count = 0

    def push(self, tx_id, destination):
        dest = int(destination)
        queue = self.groups.get(dest)
        if queue is None:
            queue = deque()
            self.groups[dest] = queue
            self.active.append(dest)
        queue.append(int(tx_id))
        self.count += 1

    def push_many(self, ids, transactions, users_per_ac):
        for tx_id in ids:
            tx_id = int(tx_id)
            destination = int(transactions[tx_id, 1]) // users_per_ac
            self.push(tx_id, destination)

    def take(self, capacity):
        if capacity < 0:
            raise ValueError('Negative local block capacity')
        selected = []
        while self.active and len(selected) < capacity:
            destination = self.active.popleft()
            queue = self.groups[destination]
            selected.append(queue.popleft())
            self.count -= 1
            if queue:
                self.active.append(destination)
            else:
                del self.groups[destination]
        return selected

    def __len__(self):
        return self.count


def pending_count(ac):
    return len(ac.queue_policy) + len(ac.current_request_collection)


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
    queue_policy: DestinationFairQueue = field(default_factory=DestinationFairQueue)
    ingested_count: int = 0
    settled_count: int = 0

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


