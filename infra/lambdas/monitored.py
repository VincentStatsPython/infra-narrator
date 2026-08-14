"""The monitored heartbeat.

This function exists to be watched. It does close to nothing on purpose:
its whole job is to run for real so CloudWatch has something true to say
about it. The load generator picks which real condition to create:

- ok (default): a pinch of genuine work, quick return
- slow: sleep a bounded number of milliseconds, stretching real Duration
- error: raise, producing a real entry in the Errors metric

Nothing here fabricates telemetry. An "error" is a real failed invocation;
"slow" is a real long one. CloudWatch only ever sees what actually happened.
"""

import random
import time

MAX_SLEEP_MS = 8000  # stay inside the 10s timeout with room to spare


def handler(event, context):
    event = event or {}
    mode = event.get("mode", "ok")

    if mode == "error":
        raise RuntimeError("deliberate fault, requested by the load generator")

    slept_ms = 0
    if mode == "slow":
        slept_ms = min(int(event.get("sleep_ms", 1500)), MAX_SLEEP_MS)
        time.sleep(slept_ms / 1000.0)

    # A little real arithmetic so Duration is a living number, not a flat line.
    n = random.randint(5_000, 40_000)
    checksum = sum(i * i for i in range(n)) % 9973

    return {"ok": True, "mode": mode, "slept_ms": slept_ms, "work_units": n,
            "checksum": checksum}
