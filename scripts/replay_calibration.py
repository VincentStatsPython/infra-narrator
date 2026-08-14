#!/usr/bin/env python3
"""Replay the REAL per-minute CloudWatch data from the step 2 load run
through the descriptor deriver, to check the thresholds separate the
conditions we actually created. Data below is copied verbatim from
docs/BUILD_LOG.md step 2; nothing here is invented.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra" / "lambdas"))
from descriptors import derive, derive_mood  # noqa: E402

# minute, condition created, invocations, errors, throttles, avg ms, max conc
REAL_MINUTES = [
    ("05:42", "quiet",    4,   0,  0,  21,   1),
    ("05:43", "quiet",    4,   0,  0,  27,   1),
    ("05:44", "steady",   24,  0,  0,  19,   2),
    ("05:45", "steady",   23,  0,  0,  621,  4),
    ("05:46", "busy",     87,  0,  0,  286,  7),
    ("05:47", "busy",     94,  0,  0,  429,  6),
    ("05:48", "degraded", 39,  5,  0,  774,  3),
    ("05:49", "degraded", 40,  5,  0,  564,  2),
    ("05:50", "incident", 116, 44, 0,  926,  9),
    ("05:51", "incident", 115, 43, 0,  898,  8),
    ("05:52", "burst",    35,  1,  16, 4892, 10),
]

print(f"{'min':5} {'created':9} {'mood':8} traffic/capacity/stability/queue")
for minute, cond, inv, errs, thr, dur, conc in REAL_MINUTES:
    m = {
        "invocations_per_min": inv,
        "error_rate": errs / inv if inv else 0.0,
        "max_concurrent": conc,
        "throttles": thr,
        "avg_duration_ms": dur,
        "minutes_since_deploy": 999,  # no deploy during the run
    }
    d = derive(m)
    lv = d["levels"]
    print(f"{minute:5} {cond:9} {derive_mood(m):8} "
          f"{lv['traffic']}/{lv['capacity']}/{lv['stability']}/{lv['queue']}")
