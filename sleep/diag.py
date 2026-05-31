# sleep/diag.py
#
# Sleep / wake diagnostics for the ESP32-P4.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI); verified v1.29.0-preview.
#
# Light sleep resumes execution in place. Deep sleep REBOOTS the chip on wake,
# so the test stashes a marker in RTC memory before sleeping; on the next boot
# check_wake() detects it (together with reset_cause == DEEPSLEEP_RESET) and
# reports how long the board was actually out. main.py calls check_wake() at
# boot so a deep-sleep test reports itself automatically after the reboot.
#
# Usage (REPL):
#   from sleep import SleepDiagnostics, main, check_wake
#   s = SleepDiagnostics()
#   s.info()              # reset cause + wake reason + RTC-memory marker
#   s.light_sleep(2000)   # sleep 2 s and resume here
#   s.deep_sleep(5)       # stash marker, sleep 5 s -> REBOOT (does not return)
#   main()                # interactive menu

import time

import machine

_MARK = b'P4SLEEP:'  # RTC-memory marker prefix for the deep-sleep test

# machine.*_RESET cause codes -> name (built from what this build exposes).
RESET_CAUSES = {}
for _n in (
    'PWRON_RESET',
    'HARD_RESET',
    'WDT_RESET',
    'DEEPSLEEP_RESET',
    'SOFT_RESET',
    'BROWNOUT_RESET',
    'LOCKUP_RESET',
):
    _c = getattr(machine, _n, None)
    if _c is not None:
        RESET_CAUSES[_c] = _n

# machine.*_WAKE wake reasons -> name.
WAKE_REASONS = {}
for _n in (
    'PIN_WAKE',
    'EXT0_WAKE',
    'EXT1_WAKE',
    'TIMER_WAKE',
    'TOUCHPAD_WAKE',
    'ULP_WAKE',
):
    _c = getattr(machine, _n, None)
    if _c is not None:
        WAKE_REASONS[_c] = _n


class SleepDiagnostics:
    # -- info ------------------------------------------------------------

    def info(self, show=True):
        cause = machine.reset_cause()
        try:
            wake = machine.wake_reason()
        except (AttributeError, OSError):
            wake = None
        try:
            mem = machine.RTC().memory()
        except (AttributeError, OSError):
            mem = b''
        info = {
            'reset_cause': cause,
            'reset_cause_name': RESET_CAUSES.get(cause, 'code({})'.format(cause)),
            'wake_reason': wake,
            'wake_reason_name': (
                WAKE_REASONS.get(wake, 'code({})'.format(wake))
                if wake is not None
                else 'n/a'
            ),
            'rtc_marker': mem.startswith(_MARK),
        }
        if show:
            print('  Reset cause: {} ({})'.format(info['reset_cause_name'], cause))
            print('  Wake reason: {}'.format(info['wake_reason_name']))
            print(
                '  RTC marker : {}'.format(
                    'present (deep-sleep test pending check)'
                    if info['rtc_marker']
                    else 'none'
                )
            )
        return info

    # -- light sleep -----------------------------------------------------

    def light_sleep(self, ms=2000, show=True):
        """Light sleep for `ms`, then resume here. Reports measured elapsed."""
        if show:
            print('  Light sleep {} ms (resumes in place)...'.format(ms))
        time.sleep_ms(50)  # let the print flush over USB
        t0 = time.ticks_ms()
        machine.lightsleep(ms)
        dt = time.ticks_diff(time.ticks_ms(), t0)
        if show:
            print('  Resumed. Measured elapsed: {} ms (requested {} ms)'.format(dt, ms))
        return {'requested_ms': ms, 'elapsed_ms': dt}

    # -- deep sleep ------------------------------------------------------

    def deep_sleep(self, seconds=5, show=True):
        """Stash a marker in RTC memory and deep-sleep. REBOOTS on wake —
        this call does not return. check_wake() reports the result at boot.
        """
        pre = time.time()
        try:
            machine.RTC().memory(_MARK + '{}:{}'.format(pre, seconds).encode())
        except (AttributeError, OSError) as e:
            print(
                "  warning: RTC memory unavailable ({}); wake won't self-report".format(
                    e
                )
            )
        if show:
            print(
                '  Deep sleep {} s. The board WILL REBOOT and the serial/REPL'.format(
                    seconds
                )
            )
            print(
                '  link will drop. Reconnect after ~{} s; the wake result'.format(
                    seconds
                )
            )
            print('  prints automatically on boot.')
        time.sleep_ms(200)  # flush prints before the radio/USB drops
        machine.deepsleep(seconds * 1000)
        # not reached

    def check_wake(self, show=True, clear=True):
        """At boot: if we woke from our deep-sleep test, report and clear it."""
        try:
            mem = machine.RTC().memory()
        except (AttributeError, OSError):
            mem = b''
        if not mem.startswith(_MARK):
            return {'woke_from_test': False}

        cause = machine.reset_cause()
        actual = req = None
        try:
            pre_s, req_s = mem[len(_MARK) :].decode().split(':')
            actual = time.time() - int(pre_s)
            req = int(req_s)
        except (ValueError, IndexError):
            pass
        if clear:
            try:
                machine.RTC().memory(b'')
            except (AttributeError, OSError):
                pass
        if show:
            print('=' * 78)
            print('Deep-sleep test: WOKE UP')
            print(
                '  Reset cause: {} ({})'.format(
                    RESET_CAUSES.get(cause, 'code({})'.format(cause)), cause
                )
            )
            if actual is not None:
                print('  Slept ~{} s (requested {} s)'.format(round(actual), req))
            ok = cause == getattr(machine, 'DEEPSLEEP_RESET', -999)
            print(
                '  Result     : {}'.format(
                    'PASS (woke via deep-sleep reset)'
                    if ok
                    else 'check: reset cause was not DEEPSLEEP_RESET'
                )
            )
            print('=' * 78)
        return {
            'woke_from_test': True,
            'reset_cause': cause,
            'slept_s': round(actual) if actual is not None else None,
            'requested_s': req,
        }

    # -- report ----------------------------------------------------------

    def report(self):
        print('=' * 78)
        print('Sleep / Wake Diagnostics — ESP32-P4 (MicroPython)')
        print('=' * 78)
        print('State:')
        self.info(show=True)
        print('\nLight sleep test:')
        self.light_sleep(2000, show=True)
        print('\n(Deep sleep is interactive — menu option 3 — since it reboots.)')
        print('=' * 78)


def check_wake(show=True):
    """Module-level convenience for main.py to call at boot."""
    return SleepDiagnostics().check_wake(show=show)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Sleep / Wake Diagnostics (ESP32-P4) ---
 1) Wake / reset info
 2) Light sleep test (resumes)
 3) Deep sleep test (REBOOTS the board!)
 0) Exit
Choose: """


def main(s=None):
    import netutils

    s = s or SleepDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return s
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(s.info)
        elif choice == '2':
            ms = input('milliseconds [2000]: ').strip()
            netutils.run_action(lambda: s.light_sleep(int(ms) if ms else 2000))
        elif choice == '3':
            sec = input('seconds [5] (board reboots!): ').strip()
            ans = input("type 'y' to confirm deep sleep: ").strip().lower()
            if ans == 'y':
                netutils.run_action(lambda: s.deep_sleep(int(sec) if sec else 5))
            else:
                print('  cancelled.')
        elif choice == '0':
            return s
        else:
            print('?')
