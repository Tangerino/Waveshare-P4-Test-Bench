# thread/diag.py
#
# Multi-threading / message-passing / parallel-performance diagnostics for the
# ESP32-P4 (dual-core RISC-V).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI); verified v1.29.0-preview.
#
# What this exercises and what to expect:
#   * _thread spawn/run  — start N workers, confirm each ran on the board.
#   * locks / races      — a shared counter, with and without a lock, proves
#                          the lock prevents lost updates.
#   * message passing    — a lock-guarded mailbox between two threads; reports
#                          throughput (msg/s) and average end-to-end latency.
#   * parallel perf      — the SAME CPU work done on 1 thread vs 2. The P4 has
#                          two cores, BUT the ESP32 port pins the interpreter and
#                          EVERY _thread to a single core (MP_TASK_COREID = core 1;
#                          core 0 is reserved for the IDF WiFi/BLE system tasks),
#                          and a global VM lock (a GIL) serialises bytecode on top
#                          of that. So pure-Python CPU work doesn't parallelise —
#                          2 threads are usually SLOWER than 1 (GIL handoffs +
#                          context switches on one core). That result is expected.
#                          (True parallelism needs native @micropython.viper / C.)
#
# Note: MicroPython's _thread has no join(); workers signal completion through a
# lock-guarded counter and the caller polls with a deadline, so a misbehaving
# worker times out cleanly instead of wedging the REPL.
#
# Usage (REPL):
#   from thread import ThreadDiagnostics, main
#   t = ThreadDiagnostics()
#   t.probe()            # is _thread available? ident / stack size
#   t.spawn(4)           # start 4 workers, confirm all ran
#   t.race(50000)        # shared counter: unlocked (racy) vs locked (correct)
#   t.messaging(5000)    # producer->consumer throughput + latency
#   t.performance()      # 1-thread vs 2-thread CPU work (shows the VM lock)
#   t.report(); main()

import gc
import time

try:
    import _thread
except ImportError:  # pragma: no cover
    _thread = None


# A CPU-bound integer kernel. Masked to 30 bits so it never grows into a
# slow arbitrary-precision bignum (same guard the system CPU bench uses).
def _burn(loops):
    x = 0
    for i in range(loops):
        x = (x + i * 3 - 1) & 0x3FFFFFFF
    return x


class _Mailbox:
    """Tiny thread-safe FIFO: lock-guarded list with a head index (no O(n)
    pop(0)). get() is non-blocking and returns None when empty."""

    def __init__(self):
        self._buf = []
        self._head = 0
        self._lock = _thread.allocate_lock()

    def put(self, item):
        with self._lock:
            self._buf.append(item)

    def get(self):
        with self._lock:
            if self._head < len(self._buf):
                item = self._buf[self._head]
                self._buf[self._head] = None  # release the reference
                self._head += 1
                return item
            return None


class ThreadDiagnostics:
    def __init__(self):
        self._lock = _thread.allocate_lock() if _thread else None

    # -- availability ----------------------------------------------------

    def _require(self):
        if _thread is None:
            raise OSError('_thread module not in this firmware')

    def probe(self, show=True):
        """Check that _thread exists and report basic facts."""
        info = {'module': _thread is not None}
        if _thread is None:
            if show:
                print('  _thread module : NOT present in this firmware')
                print('  -> multi-threading not available on this build.')
            return info
        info['ident'] = _thread.get_ident()
        try:
            info['stack'] = _thread.stack_size()
        except Exception:  # noqa: BLE001
            info['stack'] = None
        if show:
            print('  _thread module : present')
            print('  main thread id : {}'.format(info['ident']))
            if info['stack'] is not None:
                print('  default stack  : {} bytes'.format(info['stack']))
            print('  cores (P4)     : 2 (dual RISC-V), BUT all Python runs on')
            print('                   core 1 only (threads pinned to MP_TASK_COREID;')
            print(
                '                   core 0 = IDF WiFi/BLE) + a GIL serialises bytecode.'
            )
        return info

    # -- spawn / join-by-counter ----------------------------------------

    def _wait_count(self, target, get_count, timeout_ms):
        """Poll get_count() until it reaches target or the deadline passes."""
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while get_count() < target:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False
            time.sleep_ms(2)
        return True

    def spawn(self, n=4, show=True):
        """Start n worker threads; confirm every one actually ran."""
        self._require()
        done = [0]
        ran = [0]
        lock = _thread.allocate_lock()

        def worker(idx):
            _burn(2000)  # a little real work so it isn't instant
            with lock:
                ran[0] |= 1 << idx
                done[0] += 1

        t0 = time.ticks_ms()
        for i in range(n):
            _thread.start_new_thread(worker, (i,))
        ok = self._wait_count(n, lambda: done[0], timeout_ms=5000)
        dt = time.ticks_diff(time.ticks_ms(), t0)
        if show:
            print('  spawned        : {} thread(s)'.format(n))
            print('  completed      : {}/{} in {} ms'.format(done[0], n, dt))
            mask_ok = ran[0] == (1 << n) - 1
            print('  all distinct   : {}'.format('yes' if mask_ok else 'NO'))
            print(
                '  result         : {}'.format(
                    'OK' if ok else 'TIMEOUT (a worker did not finish)'
                )
            )
        return {'spawned': n, 'completed': done[0], 'ms': dt, 'ok': ok}

    # -- race / lock correctness ----------------------------------------

    def race(self, iters=200000, lock_iters=2000, threads=2, show=True):
        """Two threads += a shared counter (both pinned to core 1, GIL on).

        Unlocked: `iters` un-guarded increments per thread (fast). The GIL can
        still preempt a non-atomic read-modify-write between bytecodes, so an
        update may be lost -> total < expected (rare, timing-dependent).
        Locked: `lock_iters` guarded increments per thread (kept small because a
        *contended* lock.acquire() costs ~one RTOS tick on this port, so heavy
        locking is slow); with the lock the total is exact."""
        self._require()

        # --- unlocked (racy): many cheap increments to expose lost updates ---
        racy = [0]
        rdone = [0]
        rlock = _thread.allocate_lock()  # only guards the done counter

        def racer():
            c = racy
            for _ in range(iters):
                c[0] = c[0] + 1  # NON-atomic on purpose
            with rlock:
                rdone[0] += 1

        for _ in range(threads):
            _thread.start_new_thread(racer, ())
        self._wait_count(threads, lambda: rdone[0], timeout_ms=15000)
        racy_total = racy[0]
        racy_exp = iters * threads

        # --- locked (correct): fewer increments, each guarded by the lock ---
        safe = [0]
        sdone = [0]
        slock = _thread.allocate_lock()
        dlock = _thread.allocate_lock()

        def safer():
            for _ in range(lock_iters):
                with slock:
                    safe[0] = safe[0] + 1
            with dlock:
                sdone[0] += 1

        for _ in range(threads):
            _thread.start_new_thread(safer, ())
        locked_ok = self._wait_count(threads, lambda: sdone[0], timeout_ms=20000)
        safe_total = safe[0]
        safe_exp = lock_iters * threads

        lost = racy_exp - racy_total
        if show:
            print('  note           : threads share core 1 + a GIL (no parallelism)')
            print(
                '  no lock        : {}/{}  ({})'.format(
                    racy_total,
                    racy_exp,
                    'lost {} update(s) — RACE'.format(lost)
                    if lost
                    else 'no loss this run (VM lock hid the race)',
                )
            )
            if not locked_ok:
                state = 'incomplete — locking is slow under contention'
            elif safe_total == safe_exp:
                state = 'exact — lock works'
            else:
                state = 'WRONG'
            print('  with lock      : {}/{}  ({})'.format(safe_total, safe_exp, state))
        return {
            'racy': racy_total,
            'racy_expected': racy_exp,
            'locked': safe_total,
            'locked_expected': safe_exp,
            'locked_ok': locked_ok,
        }

    # -- message passing -------------------------------------------------

    def messaging(self, count=5000, show=True):
        """Producer thread -> consumer (here) via a lock-guarded mailbox.
        Reports throughput and average end-to-end latency."""
        self._require()
        mbox = _Mailbox()
        flag = [False]

        def producer():
            for i in range(count):
                mbox.put((i, time.ticks_us()))
            flag[0] = True

        t0 = time.ticks_us()
        _thread.start_new_thread(producer, ())

        got = 0
        lat_sum = 0
        deadline = time.ticks_add(time.ticks_ms(), 15000)
        while got < count:
            m = mbox.get()
            if m is None:
                if flag[0] and got >= count:
                    break
                if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                    break
                continue
            lat_sum += time.ticks_diff(time.ticks_us(), m[1])
            got += 1
        dt = time.ticks_diff(time.ticks_us(), t0)

        rate = (got * 1_000_000) // dt if dt else 0
        avg_lat = (lat_sum // got) if got else 0
        if show:
            print('  messages       : {}/{} delivered'.format(got, count))
            print('  elapsed        : {} ms'.format(dt // 1000))
            print('  throughput     : {} msg/s'.format(rate))
            print('  avg latency    : {} us'.format(avg_lat))
            if got < count:
                print('  result         : INCOMPLETE (timed out)')
        return {'delivered': got, 'us': dt, 'rate': rate, 'avg_lat_us': avg_lat}

    # -- parallel performance (reveals the VM lock) ---------------------

    def performance(self, loops=300_000, show=True):
        """Run the SAME total CPU work as 1 thread, then split over 2 threads,
        and compare wall-clock. Both threads share core 1 and the GIL, so the
        2-thread run gets no speedup and is usually SLOWER (handoff + context-
        switch overhead) — that's the expected result, not a bug."""
        self._require()
        gc.collect()

        # 1 thread does the whole job.
        t0 = time.ticks_ms()
        _burn(loops)
        single = time.ticks_diff(time.ticks_ms(), t0)

        # 2 threads do half each, concurrently.
        done = [0]
        lock = _thread.allocate_lock()
        half = loops // 2

        def half_job():
            _burn(half)
            with lock:
                done[0] += 1

        gc.collect()
        t0 = time.ticks_ms()
        _thread.start_new_thread(half_job, ())
        _thread.start_new_thread(half_job, ())
        ok = self._wait_count(2, lambda: done[0], timeout_ms=30000)
        dual = time.ticks_diff(time.ticks_ms(), t0)

        speedup = (single / dual) if dual else 0.0
        if speedup >= 1.6:
            verdict = 'near-linear — real parallel execution'
        elif speedup >= 1.15:
            verdict = 'partial overlap'
        elif speedup >= 0.85:
            verdict = 'no gain — serialised by the VM lock (GIL)'
        else:
            verdict = 'SLOWER — same-core time-slice: GIL handoff + switch overhead'
        if show:
            print('  workload       : {} integer ops'.format(loops))
            print('  1 thread       : {} ms'.format(single))
            print('  2 threads      : {} ms{}'.format(dual, '' if ok else ' (TIMEOUT)'))
            print('  speedup        : {:.2f}x'.format(speedup))
            print('  verdict        : {}'.format(verdict))
        return {'single_ms': single, 'dual_ms': dual, 'speedup': speedup}

    # -- report ----------------------------------------------------------

    def report(self):
        print('=' * 78)
        print('Threading Diagnostics — ESP32-P4 (dual-core RISC-V)')
        print('=' * 78)
        info = self.probe(show=True)
        if not info['module']:
            print('=' * 78)
            return
        print('\nSpawn:')
        self.spawn(4, show=True)
        print('\nLock / race:')
        self.race(50000, show=True)
        print('\nMessage passing:')
        self.messaging(5000, show=True)
        print('\nParallel performance:')
        self.performance(300_000, show=True)
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Threading Diagnostics (ESP32-P4, dual-core) ---
 1) Full report          4) Message passing (throughput/latency)
 2) Spawn N workers       5) Parallel performance (1 vs 2 threads)
 3) Lock vs race          0) Exit
Choose: """


def main(t=None):
    import netutils

    t = t or ThreadDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return t
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(t.report)
        elif choice == '2':
            n = input('threads [4]: ').strip()
            netutils.run_action(lambda: t.spawn(int(n or '4')))
        elif choice == '3':
            n = input('increments per thread [50000]: ').strip()
            netutils.run_action(lambda: t.race(int(n or '50000')))
        elif choice == '4':
            n = input('messages [5000]: ').strip()
            netutils.run_action(lambda: t.messaging(int(n or '5000')))
        elif choice == '5':
            n = input('workload loops [300000]: ').strip()
            netutils.run_action(lambda: t.performance(int(n or '300000')))
        elif choice == '0':
            return t
        else:
            print('?')
