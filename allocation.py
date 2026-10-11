"""allocation.py: deadlock with real threads, the banker's algorithm, and memory placement.

Run it from a terminal in the folder that holds this file:
    python allocation.py           (Windows)   or   python3 allocation.py   (macOS / Linux)

Your work is marked with TODO. Everything else already works: run the file before you change
anything; each experiment that reaches an unwritten TODO says which one and the rest still run.
"""

import random  # a random-number generator; given a fixed seed it produces the same numbers on every computer
import threading  # real threads and real locks, managed by the operating system
import time  # short pauses while the detector waits for the threads to get stuck


class NotWrittenYet(Exception):  # a custom error the starter raises wherever a TODO has not been written yet
    pass  # it needs no extra behavior; its name and message say everything


# ---------------------------------------------------------------------------
# Experiment 1: a real deadlock between two threads, then a fix
# ---------------------------------------------------------------------------
BALANCES = [500, 500, 500]  # three bank accounts, numbered 0, 1 and 2, each holding 500 dollars
LOCKS = [threading.Lock() for _ in BALANCES]  # one lock per account: only the thread holding it may touch that balance
TABLE_LOCK = threading.Lock()  # protects the two bookkeeping tables below, which several threads update
HOLDS = {}  # thread name -> number of the account whose lock that thread holds right now
WAITS = {}  # thread name -> number of the account whose lock that thread is waiting for right now
OUTCOME = {}  # thread name -> one line saying what the thread finally did


def note(name, holds=None, waits=None):  # records what a thread holds and waits for, so the detector can read it
    with TABLE_LOCK:  # only one thread at a time may change the tables
        HOLDS.pop(name, None)  # forget the old entries for this thread...
        WAITS.pop(name, None)  # ...in both tables
        if holds is not None:  # it holds a lock now
            HOLDS[name] = holds  # remember which one
        if waits is not None:  # it is waiting for a lock now
            WAITS[name] = waits  # remember which one


def naive_transfer(name, src, dst, amount, start_line, give_up):  # locks the source account first, then the destination
    with LOCKS[src]:  # take the first lock (mutual exclusion: nobody else may now touch account src)
        note(name, holds=src)  # tell the bookkeeping tables
        start_line.wait()  # a barrier: wait here until BOTH threads hold their first lock, so the deadlock happens every run
        note(name, holds=src, waits=dst)  # now reaching for the second lock while still holding the first (hold and wait)
        while not LOCKS[dst].acquire(timeout=0.05):  # try for the second lock, giving up for a moment every 0.05 s
            if give_up.is_set():  # the detector picked this thread as the victim of the recovery
                OUTCOME[name] = f"rolled back: released account {src}, moved nothing"  # nothing was changed, so there is nothing to undo
                note(name)  # it now holds nothing and waits for nothing
                return  # leaving the with-block releases the first lock, which unblocks the other thread
        try:  # both locks are held: the transfer can happen safely
            BALANCES[src] -= amount  # take the money out of the source account...
            BALANCES[dst] += amount  # ...and put it into the destination account
            OUTCOME[name] = f"moved {amount} from account {src} to account {dst}"  # report success
        finally:  # whatever happens above...
            LOCKS[dst].release()  # ...always give the second lock back
    note(name)  # both locks are released: this thread holds and waits for nothing


def find_cycle():  # the detector: looks for a cycle in the wait-for graph built from HOLDS and WAITS
    with TABLE_LOCK:  # read a consistent snapshot of both tables
        holder = {account: name for name, account in HOLDS.items()}  # account -> the thread holding its lock
        edges = {name: holder.get(account) for name, account in WAITS.items()}  # waiting thread -> the thread it waits for
    for first in sorted(edges):  # try starting a walk from each waiting thread, in name order
        path = [first]  # the walk so far
        while edges.get(path[-1]) is not None:  # the last thread waits for someone...
            nxt = edges[path[-1]]  # ...who is that someone?
            if nxt in path:  # we came back to a thread already on the walk: that is a cycle
                return path[path.index(nxt):] + [nxt]  # return just the cycle, with its first thread repeated at the end
            path.append(nxt)  # otherwise keep walking
    return None  # no walk came back on itself: no deadlock


def ordered_transfer(src, dst, amount):  # locks the LOWER-numbered account first, whichever way the money moves
    # TODO 1: lock the two accounts in a fixed global order, the LOWER account number first, whichever way the
    #         money moves; then, while holding both locks, take `amount` out of BALANCES[src] and add it to
    #         BALANCES[dst]. Use two nested `with LOCKS[...]:` blocks, like the single one in naive_transfer.
    first = min(src, dst)
    second = max(src, dst)

    with LOCKS[first]:
        with LOCKS[second]:
            BALANCES[src] -= amount
            BALANCES[dst] += amount

def ordered_worker(src, dst, times):  # a thread body: many small transfers in one direction
    for _ in range(times):  # repeat the transfer `times` times
        ordered_transfer(src, dst, 1)  # one dollar each time


class RecordingLock:  # a stand-in for a real lock that only writes down when it is taken; the lock-order check uses it
    def __init__(self, account, log):  # account: the account this lock guards; log: a list shared by all the stand-ins
        self.account = account  # remember the account number
        self.log = log  # remember the shared list
    def acquire(self, *args, **kwargs):  # called directly, or by a with-block through __enter__ below
        self.log.append(self.account)  # write down that this account's lock was taken now
        return True  # a real lock also returns True when it has been taken
    def release(self):  # giving the lock back needs no record
        pass  # nothing to do
    def __enter__(self):  # `with lock:` calls this on the way in...
        return self.acquire()  # ...which is the same as taking the lock
    def __exit__(self, *exc):  # ...and this on the way out
        self.release()  # the same as giving it back
        return False  # never hide an error raised inside the with-block


def check_lock_order():  # checks TODO 1 without depending on timing: which lock does ordered_transfer take first?
    real = LOCKS[:]  # keep the real locks so they can be put back afterwards
    try:  # whatever happens below, the finally block restores the real locks
        for src, dst in ((0, 1), (2, 0)):  # one transfer up the account numbers and one down
            log = []  # the order in which locks are taken during this one call
            LOCKS[:] = [RecordingLock(i, log) for i in range(len(real))]  # swap in the recording stand-ins
            ordered_transfer(src, dst, 0)  # a zero-dollar transfer, so no balance changes
            want = sorted({src, dst})  # the right order: the lower account number first
            if log != want:  # the locks were taken in another order, or they were not exactly these two
                if len(log) == 2:  # two locks, in the wrong order
                    print(f"  lock-order check: TODO 1 is wrong: for a transfer from {src} to {dst} you locked account {log[0]} before account {log[1]}")  # say exactly what happened
                else:  # too few or too many locks
                    print(f"  lock-order check: TODO 1 is wrong: for a transfer from {src} to {dst} you took the locks {log}; take account {want[0]}, then account {want[1]}")  # say what was expected
                return False  # report failure; the ring is then skipped
    finally:  # always...
        LOCKS[:] = real  # ...put the real locks back
    print("  lock-order check: PASS (a transfer from 2 to 0 locks account 0 first, then account 2)")  # the right order
    return True  # the ring can run safely


def experiment_deadlock():  # part 1: produce, detect and recover from a deadlock; part 2: prevent it by ordering
    print("Experiment 1: two threads take two locks in opposite orders")  # a title
    start_line = threading.Barrier(2)  # both threads must reach the barrier before either goes on
    give_up = {"T1": threading.Event(), "T2": threading.Event()}  # one "you are the victim" flag per thread
    plan = {"T1": (0, 1, 100), "T2": (1, 0, 50)}  # T1 moves 100 from account 0 to 1; T2 moves 50 from account 1 to 0
    threads = [threading.Thread(target=naive_transfer, args=(n, s, d, a, start_line, give_up[n])) for n, (s, d, a) in plan.items()]  # one thread per plan
    for t in threads:  # start both
        t.start()  # each now runs naive_transfer
    cycle = None  # nothing found yet
    for _ in range(40):  # look every 0.05 s, for at most 2 seconds
        time.sleep(0.05)  # give the threads time to get stuck
        cycle = find_cycle()  # run the detector
        if cycle:  # a cycle means a deadlock
            break  # stop looking
    with TABLE_LOCK:  # print what each thread holds and wants, from the same tables the detector used
        for name in sorted(WAITS):  # in name order, so every run prints the same lines
            print(f"  {name} holds the lock of account {HOLDS[name]} and waits for the lock of account {WAITS[name]}")  # one line per thread
    if cycle:  # the expected case
        print(f"  deadlock detected: {' -> '.join(cycle)} (each thread waits for a lock the next one holds)")  # the cycle
        victim = min(cycle[:-1], key=lambda n: plan[n][2])  # recovery: roll back the thread moving the least money (the cheapest to redo)
        print(f"  recovery: {victim} is chosen as the victim (it moves less money, so it is the cheaper one to redo)")  # explain the choice
        give_up[victim].set()  # tell the victim to give up its lock
    for t in threads:  # wait for both threads to end
        t.join()  # one finishes its transfer, the other gives up
    for name in sorted(OUTCOME):  # report what each thread did
        print(f"  {name}: {OUTCOME[name]}")  # one line each
    print(f"  balances {BALANCES}, total {sum(BALANCES)}")  # the total must still be 1500

    print("\n  Prevention: every thread locks the lower-numbered account first (three threads in a ring)")  # the second half
    BALANCES[:] = [500, 500, 500]  # reset the accounts
    if not check_lock_order():  # check the lock order first (this also stops here with a message if TODO 1 is not written yet)
        return  # a wrong order could freeze the ring below, so the ring is skipped
    ring = [(0, 1), (1, 2), (2, 0)]  # T1 pays 0 -> 1, T2 pays 1 -> 2, T3 pays 2 -> 0: a ring, the shape a circular wait needs
    times = 20_000  # transfers per thread
    workers = [threading.Thread(target=ordered_worker, args=(s, d, times)) for s, d in ring]  # one thread per direction
    for t in workers:  # start all three
        t.start()  # they now compete for the locks
    for t in workers:  # wait for all three
        t.join()  # join() returns only when that thread has finished every transfer
    print(f"  {len(ring) * times:,} transfers finished, balances {BALANCES}, total {sum(BALANCES)} (started at 1500)")  # nobody got stuck


# ---------------------------------------------------------------------------
# Experiment 2: the banker's algorithm
# ---------------------------------------------------------------------------
TOTAL = [9, 5, 6]  # units of each resource type (A, B, C) the system owns
CLAIM = [[7, 1, 1], [4, 3, 3], [2, 3, 5], [4, 1, 4]]  # CLAIM[i]: the most of each type process P(i+1) declared it may ever hold
ALLOC = [[1, 0, 0], [4, 3, 1], [0, 1, 0], [1, 0, 1]]  # ALLOC[i]: what process P(i+1) holds right now


def available_units():  # free units of each type = total minus everything allocated
    return [TOTAL[j] - sum(row[j] for row in ALLOC) for j in range(len(TOTAL))]  # one number per resource type


def is_safe(available, claim, alloc):  # the safety test: returns a safe order of process numbers, or None if there is none
    # TODO 2: start with work = a copy of `available` and nobody finished. Repeat: find the LOWEST-numbered
    #         unfinished process whose remaining need (claim minus alloc, for every type) fits in work; pretend
    #         it finishes: add its alloc row to work, mark it finished, append its number (i + 1) to the order,
    #         and search again from the lowest number. Return the order once everyone has finished, or None
    #         as soon as nobody can finish. (Problem 2 practises this by hand.)
    work = available.copy()
    finished = [False] * len(claim)
    order = []

    while len(order) < len(claim):
        found = False

        for i in range(len(claim)):
            if finished[i]:
                continue

            need = [
                claim[i][j] - alloc[i][j]
                for j in range(len(work))
            ]

            if all(need[j] <= work[j] for j in range(len(work))):
                for j in range(len(work)):
                    work[j] += alloc[i][j]

                finished[i] = True
                order.append(i + 1)
                found = True
                break

        if not found:
            return None
        
    return order

def request(i, req):  # process P(i+1) asks for the units in req; returns one line saying what happened
    if any(ALLOC[i][j] + req[j] > CLAIM[i][j] for j in range(len(req))):  # it would hold more than it declared
        return "error: more than its declared claim"  # a broken promise, not a scheduling question
    avail = available_units()  # what is free right now
    if any(req[j] > avail[j] for j in range(len(req))):  # the units simply are not there
        return f"must wait: only {avail} free"  # the process blocks until someone releases units
    for j in range(len(req)):  # pretend to grant it...
        ALLOC[i][j] += req[j]  # ...by adding the units to its allocation
    order = is_safe(available_units(), CLAIM, ALLOC)  # would the new state still be safe?
    if order is None:  # no: granting could lead to deadlock
        for j in range(len(req)):  # undo the pretend grant
            ALLOC[i][j] -= req[j]  # take the units back
        return "refused: the state would be unsafe (the process waits)"  # the units were free, but the banker says no
    return f"granted; a safe order is {' '.join('P' + str(k) for k in order)}"  # yes: keep the grant


def finish(i):  # process P(i+1) ends and releases everything
    released = ALLOC[i]  # what it held
    ALLOC[i] = [0] * len(TOTAL)  # it holds nothing now
    CLAIM[i] = [0] * len(TOTAL)  # and will never ask for anything again
    return f"finishes and releases {released}"  # report it


def experiment_banker():  # replays a list of events through the banker
    print("\nExperiment 2: the banker's algorithm (resource types A, B, C)")  # a title
    print(f"  total {TOTAL}, free {available_units()}")  # the starting vectors
    order = is_safe(available_units(), CLAIM, ALLOC)  # is the starting state safe?
    print(f"  starting state: {'safe, order ' + ' '.join('P' + str(k) for k in order) if order else 'UNSAFE'}")  # report
    events = [("req", 2, [2, 0, 2]), ("req", 0, [0, 2, 1]), ("req", 0, [0, 1, 1]),  # the event list: requests...
              ("req", 3, [2, 0, 2]), ("end", 2, None), ("req", 0, [0, 1, 1])]  # ...one finish, and a request made a second time
    for kind, i, req in events:  # handle each event in order
        if kind == "req":  # a request
            print(f"  P{i + 1} asks for {req}: {request(i, req)}")  # what the banker decided
        else:  # a process ends
            print(f"  P{i + 1} {finish(i)}")  # what it released
    print(f"  final free {available_units()}")  # what is left at the end


# ---------------------------------------------------------------------------
# Experiment 3: placement algorithms for dynamic partitioning
# ---------------------------------------------------------------------------
MEMORY_KB = 2048  # the size of the memory being shared out (above the operating system), in KB
STEPS = 3000  # how many requests the workload makes
SEED = 2026  # the random seed: the same seed gives the same workload on every computer
SIZES = (10, 200)  # each request asks for between 10 and 200 KB (every size in between equally likely)
LIFETIMES = (10, 50)  # each placed block stays in memory for 10 to 50 steps


def first_fit(holes, size, pointer):  # takes the first hole, from the bottom of memory, that is big enough
    examined = 0  # how many holes we looked at
    for i, (start, length) in enumerate(holes):  # holes are [start, length] pairs in address order
        examined += 1  # we looked at one more hole
        if length >= size:  # it is big enough
            return i, examined  # use it
    return None, examined  # no hole is big enough


def worst_fit(holes, size, pointer):  # takes the LARGEST hole, so the piece left over is as big as possible
    examined, choice = 0, None  # nothing chosen yet
    for i, (start, length) in enumerate(holes):  # every hole must be looked at to know which is largest
        examined += 1  # we looked at one more hole
        if length >= size and (choice is None or length > holes[choice][1]):  # bigger than the best so far (ties keep the lower address)
            choice = i  # remember it
    return choice, examined  # the largest hole, or None if none is big enough


def best_fit(holes, size, pointer):  # takes the SMALLEST hole that is big enough, so the leftover is as small as possible
    # TODO 3a: copy the body of worst_fit and change one comparison so it keeps the SMALLEST hole that fits.
    examined = 0
    choice = None

    for i, (start, length) in enumerate(holes):
        examined += 1

        if length >= size and (choice is None or length < holes[choice][1]):
            choice = i

    return choice, examined

def next_fit(holes, size, pointer):  # like first-fit, but starts where the last placement ended and wraps around
    # TODO 3b: find `begin`, the index of the first hole whose start is at or above `pointer` (use 0 if there is
    #         none). Look at the holes in the order begin, begin + 1, ..., wrapping past the last hole back to
    #         hole 0, each one once. Count every hole you look at, and return (index, examined) for the first one
    #         that is big enough, or (None, examined) after a full lap. An empty list returns (None, 0).
    if not holes:
        return None, 0

    begin = 0

    for i, (start, length) in enumerate(holes):
        if start >= pointer:
            begin = i
            break

    examined = 0

    for offset in range(len(holes)):
        i = (begin + offset) % len(holes)
        examined += 1

        if holes[i][1] >= size:
            return i, examined

    return None, examined


def free_block(holes, start, size):  # returns a block to the free list and merges it with free neighbors
    holes.append([start, size])  # add the block as a hole...
    holes.sort()  # ...and keep the list in address order
    merged = []  # the list after merging
    for hole in holes:  # walk up through memory
        if merged and merged[-1][0] + merged[-1][1] == hole[0]:  # this hole starts exactly where the previous one ends
            merged[-1][1] += hole[1]  # join them into one bigger hole
        else:  # not touching
            merged.append(hole)  # keep it separate
    holes[:] = merged  # replace the list in place


def simulate(policy):  # runs the whole workload with one placement policy and returns its statistics
    rng = random.Random(SEED)  # a private generator, so every policy sees exactly the same requests
    holes = [[0, MEMORY_KB]]  # at the start, all of memory is one big hole
    live = []  # blocks in use, as [time it leaves, start, size]
    pointer = 0  # where the last placement ended (only next-fit uses it)
    failed = failed_fragmented = examined = 0  # counters
    hole_count = hole_size = largest = 0  # running sums for the averages
    for step in range(STEPS):  # one request per step
        for block in [b for b in live if b[0] == step]:  # blocks whose lifetime is over...
            live.remove(block)  # ...leave memory...
            free_block(holes, block[1], block[2])  # ...and become holes again
        size = rng.randint(*SIZES)  # the new request, in KB
        life = rng.randint(*LIFETIMES)  # how many steps it stays in memory once placed
        choice, looked = policy(holes, size, pointer)  # ask the policy for a hole
        examined += looked  # count the search effort
        if choice is None:  # no hole is big enough
            failed += 1  # the request fails
            if sum(length for _, length in holes) >= size:  # yet the free memory added up to enough
                failed_fragmented += 1  # that failure is caused by external fragmentation
        else:  # place the block at the bottom of the chosen hole
            start = holes[choice][0]  # where it goes
            holes[choice][0] += size  # the hole now starts higher up...
            holes[choice][1] -= size  # ...and is smaller
            if holes[choice][1] == 0:  # an exact fit leaves nothing behind
                holes.pop(choice)  # so that hole disappears
            live.append([step + life, start, size])  # remember when it leaves
            pointer = start + size  # next-fit continues from here
        hole_count += len(holes)  # sample the free list after every step
        hole_size += sum(length for _, length in holes) / max(1, len(holes))  # average hole size right now
        largest += max((length for _, length in holes), default=0)  # largest hole right now
    return failed, failed_fragmented, hole_count / STEPS, hole_size / STEPS, largest / STEPS, examined / STEPS  # the averages


def experiment_placement():  # checks each policy on a tiny case, then runs the workload with each
    print(f"\nExperiment 3: placement in {MEMORY_KB} KB, {STEPS} requests of {SIZES[0]}-{SIZES[1]} KB (seed {SEED})")  # a title
    tiny = [[0, 100], [200, 70], [400, 300], [800, 60]]  # four holes: [start, size] in KB
    expect = {"first-fit": 0, "best-fit": 800, "next-fit": 200, "worst-fit": 400}  # the right answers for a 55 KB request
    policies = {"first-fit": first_fit, "best-fit": best_fit, "next-fit": next_fit, "worst-fit": worst_fit}  # name -> function
    for name, policy in policies.items():  # self-check each policy on the tiny case, pointer at 150
        try:  # an unwritten policy raises NotWrittenYet
            i, _ = policy([h[:] for h in tiny], 55, 150)  # ask for 55 KB
            got = tiny[i][0] if i is not None else None  # the start of the chosen hole
            print(f"  self-check {name:<9} 55 KB with the pointer at 150 -> hole at {got} (expected {expect[name]})")  # compare
        except NotWrittenYet as missing:  # this policy is not written yet
            print(f"  self-check {name:<9} -> stopped here: {missing}")  # say so
    print(f"  {'policy':<10}{'failed':>7}{'of them fragmented':>20}{'avg holes':>11}{'avg hole KB':>13}{'avg largest KB':>16}{'holes examined':>16}")  # table header
    for name, policy in policies.items():  # the full workload under each policy
        try:  # an unwritten policy raises NotWrittenYet
            f, ff, h, s, big, ex = simulate(policy)  # run it
            print(f"  {name:<10}{f:>7}{ff:>20}{h:>11.1f}{s:>13.1f}{big:>16.1f}{ex:>16.2f}")  # one row of the table
        except NotWrittenYet as missing:  # skipped
            print(f"  {name:<10} -> stopped here: {missing}")  # say which TODO


def main():  # runs the experiments in order
    for experiment in (experiment_deadlock, experiment_banker, experiment_placement):  # 1, 2, 3 in order
        try:  # run one experiment
            experiment()  # if it reaches an unwritten TODO, NotWrittenYet jumps to the except below
        except NotWrittenYet as missing:  # a TODO was reached
            print(f"  -> stopped here: {missing}")  # say which one, then carry on with the next experiment


if __name__ == "__main__":  # true when this file is run directly, false if another program imports it
    main()  # start the program
