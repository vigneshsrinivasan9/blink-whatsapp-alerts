"""24x7 supervisor for the Blink -> WhatsApp monitor.

Runs `run_all.py` (cloudflared tunnel + monitor) as a child process and
**restarts it automatically** whenever it exits for any reason, using
exponential backoff so a persistent failure (e.g. network outage) doesn't spin
the CPU. Each restart brings up a fresh tunnel URL, which `run_all.py` captures
automatically.

It also asks Windows to keep the machine awake while running, so an idle PC
doesn't sleep and miss motion events.

Run it directly:
    python supervisor.py

Or install it to start at boot with install_service.ps1 (recommended for 24x7).
Stop with Ctrl+C.
"""
import ctypes
import logging
import os
import signal
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s supervisor %(message)s",
)
log = logging.getLogger("supervisor")

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "run_all.py")

MIN_BACKOFF = 5         # seconds
MAX_BACKOFF = 300       # cap restart delay at 5 minutes
RESET_AFTER = 120       # if a child ran longer than this, treat it as healthy

# Windows SetThreadExecutionState flags: keep system (and optionally display)
# awake while the supervisor runs.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _keep_awake() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
            log.info("Requested Windows to keep the system awake.")
        except Exception:  # noqa: BLE001
            log.warning("Could not set keep-awake state.", exc_info=True)


def _allow_sleep() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    _keep_awake()
    log.info("Supervisor started. Target: %s", TARGET)

    backoff = MIN_BACKOFF
    child: subprocess.Popen | None = None

    def _shutdown(signum, frame):  # noqa: ANN001, ARG001
        log.info("Signal %s received -> stopping child and exiting.", signum)
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        _allow_sleep()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            started = time.time()
            log.info("Launching monitor (%s)...", os.path.basename(TARGET))
            child = subprocess.Popen([sys.executable, TARGET], cwd=HERE)
            code = child.wait()
            ran_for = time.time() - started
            log.warning("Monitor exited (code=%s) after %.0fs.", code, ran_for)

            # Healthy long run -> reset backoff. Quick crash -> back off more.
            if ran_for >= RESET_AFTER:
                backoff = MIN_BACKOFF
            else:
                backoff = min(backoff * 2, MAX_BACKOFF)

            log.info("Restarting in %ds...", backoff)
            time.sleep(backoff)
    finally:
        _allow_sleep()


if __name__ == "__main__":
    sys.exit(main())
