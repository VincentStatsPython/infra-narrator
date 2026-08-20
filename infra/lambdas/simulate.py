"""The simulator: pick a condition, hear the machine speak from inside it.

The scheduled narrator only ever describes the present, and the present is
usually quiet. This endpoint lets a visitor choose a condition instead and
get a poem written from it, using the same descriptor pool, the same prompt
and the same model chain as the real narrator.

The numbers are not invented. Each state replays REAL per-minute CloudWatch
data recorded from inr-monitored-dev during the step 2 calibration run (see
docs/BUILD_LOG.md), one real minute picked per request:

  stable      the measured steady minutes, 24/min, zero errors
  unstable    the measured incident and burst minutes, ~38% real errors,
              concurrency pinned at the account cap, 16 real throttles
  recovering  the one state the calibration run never captured, because the
              load generator stopped rather than tapered. Composed from the
              measured endpoints instead: traffic fallen back into the
              recorded quiet-to-steady band, errors decayed to a trace,
              throttles cleared, and a recent deploy. Marked composed=True
              below so nobody mistakes it for a recording.

Every response carries simulated=True, and simulated poems are stored under
their own key so they never enter the real history the panel shows.
"""

import json
import os
import random
import time
from datetime import datetime, timezone

import boto3

from descriptors import derive, derive_mood
from poem_model import PoemError, generate_poem

TABLE_NAME = os.environ["TABLE_NAME"]
# One poem per state per cooldown: this route spends model quota, and it is
# open to anyone with the page. Repeat clicks inside the window replay the
# poem already written rather than buying a new one.
COOLDOWN_S = int(os.environ.get("SIM_COOLDOWN_S", "45"))
SIM_KEEP_S = 3600

_table = boto3.resource("dynamodb").Table(TABLE_NAME)

# invocations, errors, throttles, avg ms, max concurrent, minutes since deploy
STATES = {
    "stable": {
        "label": "STABLE",
        "composed": False,
        "source": "calibration 05:44-05:45, steady load",
        "minutes": [
            (24, 0, 0, 19, 2, 999),
            (23, 0, 0, 621, 4, 999),
        ],
    },
    "unstable": {
        "label": "UNSTABLE",
        "composed": False,
        "source": "calibration 05:50-05:52, incident load and the burst",
        "minutes": [
            (116, 44, 0, 926, 9, 999),
            (115, 43, 0, 898, 8, 999),
            (35, 1, 16, 4892, 10, 999),
        ],
    },
    "recovering": {
        "label": "RECOVERING",
        "composed": True,
        "source": "composed between the recorded quiet and steady baselines",
        "minutes": [
            (32, 1, 0, 512, 3, 9),
            (26, 0, 0, 340, 2, 16),
            (31, 1, 0, 287, 3, 22),
        ],
    },
}


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body),
    }


def _metrics(minute):
    inv, err, thr, dur, conc, age = minute
    return {
        "invocations_per_min": float(inv),
        "error_rate": err / inv if inv else 0.0,
        "max_concurrent": float(conc),
        "throttles": float(thr),
        "avg_duration_ms": float(dur),
        "minutes_since_deploy": float(age),
        "window_min": 1,
    }


def _cached(state):
    item = _table.get_item(Key={"pk": "SIM", "sk": state}).get("Item")
    if not item:
        return None
    record = json.loads(item["body"])
    if time.time() - float(item["written_at"]) > COOLDOWN_S:
        return None
    record["cached"] = True
    return record


def _store(state, record):
    _table.put_item(Item={
        "pk": "SIM", "sk": state,
        "written_at": str(time.time()),
        "expires_at": int(time.time()) + SIM_KEEP_S,
        "body": json.dumps(record),
    })


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return _resp(400, {"error": "body must be JSON"})

    state = str(body.get("state", "")).lower()
    if state not in STATES:
        return _resp(400, {"error": "unknown state",
                           "states": sorted(STATES)})

    hit = _cached(state)
    if hit:
        return _resp(200, hit)

    spec = STATES[state]
    metrics = _metrics(random.choice(spec["minutes"]))
    derived = derive(metrics)
    mood = derive_mood(metrics)

    try:
        result = generate_poem(mood, derived)
    except PoemError as exc:
        return _resp(503, {"error": f"poem generation failed: {exc}"})

    record = {
        "simulated": True,
        "state": state,
        "state_label": spec["label"],
        "composed": spec["composed"],
        "source": spec["source"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mood": mood,
        "metrics": metrics,
        "levels": derived["levels"],
        "poem": result["poem"],
        "model": result["model"],
        "cached": False,
    }
    _store(state, record)
    return _resp(200, record)
