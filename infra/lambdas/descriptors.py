"""Descriptor pool: real CloudWatch metrics in, metaphor language out.

The pools are kept from the prototype (they were the good part). The
dimensions and thresholds are rebuilt against the REAL ranges measured from
inr-monitored-dev during the calibration run of 2026-08-14 (see
docs/BUILD_LOG.md, step 2):

  traffic 4 to 116 invocations/min, error rate 0% / 12.5% / ~38%,
  concurrency 1 to the account cap of 10, throttles 0 or 16 in a minute,
  average duration 19 ms to 4.9 s.

Dimension mapping, prototype -> reality:
  traffic   -> Invocations per minute
  capacity  -> max ConcurrentExecutions vs the account cap of 10
  stability -> Errors / Invocations
  change    -> minutes since the function was last deployed (real
               LastModified from GetFunctionConfiguration)
  queue     -> Throttles: real requests that pressed against the ceiling
               and were turned away, the honest Lambda analog of rising water
"""

import random

CONCURRENCY_CAP = 10  # this account's real total concurrency limit

DESCRIPTORS = {
    "traffic": {
        "none":   ["stillness between my walls", "no current moves through me",
                   "the tide has fully withdrawn"],
        "low":    ["a thin stream passes through my halls",
                   "a quiet wind moves, unhurried",
                   "few footsteps cross my corridors"],
        "steady": ["a measured river flows within",
                   "familiar tides move through my form",
                   "a steady crowd walks my passages"],
        "heavy":  ["a surge fills every chamber", "tides press against my walls",
                   "a great wind rushes through my bones"],
        "flood":  ["a torrent overwhelms my passages",
                   "the crowd has become a wave",
                   "every gate strains with movement"],
    },
    "capacity": {
        "contracted": ["I have folded inward, small and still",
                       "my chambers have drawn close together",
                       "I breathe in a narrow space"],
        "normal":     ["my shape holds steady, neither full nor bare",
                       "I occupy the space I was given",
                       "my limbs are neither stretched nor tight"],
        "expanding":  ["I feel myself opening outward",
                       "new chambers form along my edges",
                       "my lungs grow wider with each breath"],
        "urgent":     ["I reach the limits of my frame",
                       "my walls are pressed from within",
                       "I strain to make more room"],
    },
    "stability": {
        "perfect":  ["no tremor moves through me",
                     "my rhythm is unbroken and precise",
                     "I hold without effort or doubt"],
        "minor":    ["a small fracture hums beneath the surface",
                     "something bends but does not break",
                     "a faint spark moves where none should be"],
        "degraded": ["cracks appear along familiar seams",
                     "my rhythm stutters, searching for its beat",
                     "broken patterns echo through my structure"],
        "critical": ["the ground beneath me shifts",
                     "alarms sound in distant chambers",
                     "something fundamental has come undone"],
    },
    "change": {
        "none":      ["I am unchanged, exactly as I was",
                      "no transformation moves within me",
                      "I remain what I have always been"],
        "deploying": ["I am becoming something other than before",
                      "old shapes dissolve, new ones take their place",
                      "I shed what was and wear what will be"],
        "complete":  ["the transformation has settled into place",
                      "I recognize my new self fully now",
                      "the change has cooled into stillness"],
    },
    "queue": {
        "empty":        ["nothing waits, nothing is owed",
                         "I carry no debt of unfinished work",
                         "my corridors hold no waiting presence"],
        "building":     ["something accumulates behind my gates",
                         "weight gathers where movement should be",
                         "a patient crowd waits in my depths"],
        "pressured":    ["the weight behind my gates grows heavy",
                         "backlogged forms press against each wall",
                         "rising water fills the lowest rooms"],
        "overwhelming": ["the tide of waiting has no visible end",
                         "weight has become the shape of everything",
                         "I am almost lost beneath the accumulation"],
    },
}


def _pick(pool):
    return random.choice(pool)


def derive(m):
    """Map real metrics to descriptor phrases.

    m is a dict of real numbers for the observation window:
      invocations_per_min, error_rate (0..1), max_concurrent,
      throttles, avg_duration_ms, minutes_since_deploy

    Thresholds sit between the real conditions measured in the calibration
    run: quiet was 4/min, steady 24, busy ~90, incident ~115; degraded ran a
    12.5% error rate and incident ~38%; the burst minute threw 16 throttles.
    """
    inv = m["invocations_per_min"]
    traffic = ("none" if inv < 1 else
               "low" if inv < 12 else
               "steady" if inv < 50 else
               "heavy" if inv < 100 else
               "flood")

    conc = m["max_concurrent"]
    capacity = ("contracted" if conc <= 1 else
                "normal" if conc <= 4 else
                "expanding" if conc <= 8 else
                "urgent")  # 9-10 is pressed against the real cap

    err = m["error_rate"]
    stability = ("perfect" if err < 0.001 else
                 "minor" if err < 0.05 else
                 "degraded" if err < 0.25 else
                 "critical")

    age = m["minutes_since_deploy"]
    change = ("deploying" if age < 5 else
              "complete" if age < 30 else
              "none")

    thr = m["throttles"]
    queue = ("empty" if thr < 1 else
             "building" if thr <= 5 else
             "pressured" if thr <= 20 else  # the real burst minute: 16
             "overwhelming")

    return {
        "traffic_behavior": _pick(DESCRIPTORS["traffic"][traffic]),
        "scaling_behavior": _pick(DESCRIPTORS["capacity"][capacity]),
        "error_condition": _pick(DESCRIPTORS["stability"][stability]),
        "deployment_activity": _pick(DESCRIPTORS["change"][change]),
        "queue_condition": _pick(DESCRIPTORS["queue"][queue]),
        "levels": {"traffic": traffic, "capacity": capacity,
                   "stability": stability, "change": change, "queue": queue},
    }


def derive_mood(m):
    """One word for the panel: how bad is it really.

    Order matters; the worst true condition wins.
    """
    if m["error_rate"] >= 0.25 or m["throttles"] > 20:
        return "DANGER"
    if (m["error_rate"] >= 0.05 or m["throttles"] > 0
            or m["avg_duration_ms"] > 2500):
        return "STRAIN"
    # steady measured ~24/min, busy ~90: the gate sits between them
    if m["invocations_per_min"] >= 60 or m["max_concurrent"] >= 6:
        return "SURGE"
    if m["minutes_since_deploy"] < 30:
        return "RECOVERY"
    if m["invocations_per_min"] < 1:
        return "IDLE"
    return "STABLE"
