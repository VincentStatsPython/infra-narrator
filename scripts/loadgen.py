#!/usr/bin/env python3
"""Load generator for the monitored heartbeat.

Sends REAL requests at inr-monitored-dev at a chosen rate, with a chosen
share of deliberate errors and slow calls. This is the only place where
conditions are decided; CloudWatch just records what actually happens.

Scenarios (rates sized for a tiny dedicated Lambda, not a production fleet):

  quiet     a few invocations per minute, all healthy
  steady    a couple dozen per minute, the odd slow call
  busy      ~90 per minute, mostly healthy, some slow
  degraded  moderate rate with a real 15% failure share
  incident  high rate, ~40% failures, slow calls, plus a concurrent burst
            of long sleeps that exceeds the account's concurrency cap of 10
            to produce genuine Throttles

Usage:
  python3 loadgen.py quiet steady busy          # run scenarios in order
  python3 loadgen.py incident --minutes 2       # override phase length
"""

import argparse
import concurrent.futures
import json
import random
import sys
import time
from datetime import datetime, timezone

import boto3

FUNCTION = "inr-monitored-dev"

SCENARIOS = {
    "quiet":    dict(rpm=4,   error_pct=0,  slow_pct=0,  burst=False),
    "steady":   dict(rpm=24,  error_pct=0,  slow_pct=5,  burst=False),
    "busy":     dict(rpm=90,  error_pct=1,  slow_pct=10, burst=False),
    "degraded": dict(rpm=40,  error_pct=15, slow_pct=20, burst=False),
    "incident": dict(rpm=120, error_pct=40, slow_pct=30, burst=True),
}

BURST_SIZE = 25       # concurrent slow calls; account cap is 10, so real throttles
BURST_SLEEP_MS = 6000


def utcnow():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def invoke(client, payload):
    """One real invocation. Returns 'ok', 'error', or 'throttled'."""
    try:
        resp = client.invoke(FunctionName=FUNCTION,
                             Payload=json.dumps(payload).encode())
        if resp.get("FunctionError"):
            return "error"
        return "ok"
    except client.exceptions.TooManyRequestsException:
        return "throttled"
    except Exception as exc:  # noqa: BLE001 - count it, keep the run going
        print(f"    unexpected invoke failure: {exc}", file=sys.stderr)
        return "failed"


def pick_payload(cfg):
    roll = random.uniform(0, 100)
    if roll < cfg["error_pct"]:
        return {"mode": "error"}
    if roll < cfg["error_pct"] + cfg["slow_pct"]:
        return {"mode": "slow", "sleep_ms": random.randint(1000, 5000)}
    return {"mode": "ok"}


def run_scenario(name, minutes):
    cfg = SCENARIOS[name]
    client = boto3.client("lambda")
    counts = {"ok": 0, "error": 0, "throttled": 0, "failed": 0}
    total = cfg["rpm"] * minutes
    interval = 60.0 / cfg["rpm"]

    print(f"[{utcnow()}] scenario '{name}': {cfg['rpm']}/min for {minutes} min "
          f"({cfg['error_pct']}% errors, {cfg['slow_pct']}% slow)")

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = []
        for i in range(total):
            futures.append(pool.submit(invoke, client, pick_payload(cfg)))
            # jittered pacing so traffic looks like traffic, not a metronome
            time.sleep(interval * random.uniform(0.5, 1.5))
        if cfg["burst"]:
            print(f"[{utcnow()}]   burst: {BURST_SIZE} concurrent "
                  f"{BURST_SLEEP_MS}ms sleeps against a cap of 10")
            burst_payload = {"mode": "slow", "sleep_ms": BURST_SLEEP_MS}
            futures += [pool.submit(invoke, client, burst_payload)
                        for _ in range(BURST_SIZE)]
        for f in concurrent.futures.as_completed(futures):
            counts[f.result()] += 1

    print(f"[{utcnow()}]   done: {counts}")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="+", choices=sorted(SCENARIOS))
    parser.add_argument("--minutes", type=int, default=2,
                        help="length of each scenario phase (default 2)")
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"run started {started}")
    grand = {"ok": 0, "error": 0, "throttled": 0, "failed": 0}
    for name in args.scenarios:
        counts = run_scenario(name, args.minutes)
        for k, v in counts.items():
            grand[k] += v
    print(f"run finished {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"totals: {grand}")


if __name__ == "__main__":
    main()
