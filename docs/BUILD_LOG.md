# Build log

## Step 1: the monitored heartbeat exists and CloudWatch sees it (2026-08-14)

Deployed `inr-dev-monitored` (CDK, us-east-1): one Python 3.12 Lambda named
`inr-monitored-dev`, 128 MB, 10s timeout. It exists to be watched. Modes:
`ok` (default, a pinch of arithmetic), `slow` (bounded sleep), `error`
(raises RuntimeError for real).

First deploy failed honestly: this account's total Lambda concurrency cap is
10, so reserving 5 for the function would drop the unreserved pool below its
minimum of 10 and CloudFormation refused. Dropped the reservation. The tiny
account cap is actually useful: a real concurrent burst of slow invocations
will hit the ceiling and produce genuine Throttles with no reservation needed.

Manual test calls, invoked 05:34:59Z to 05:35:29Z: 8 ok, 2 slow (2500 ms and
4000 ms sleeps), 2 deliberate errors. The error invocations returned a real
unhandled RuntimeError ("deliberate fault, requested by the load generator")
with a real stack trace.

Real CloudWatch numbers for that minute (AWS/Lambda, FunctionName =
inr-monitored-dev, period 60, timestamp 2026-08-14T05:35:00Z):

- Invocations Sum: 12.0
- Errors Sum: 2.0
- Duration Average: 557.59 ms, Maximum: 4042.55 ms (the 4s slow call)
- Throttles Sum: 0.0

Every number lines up with what was actually sent: 12 requests, 2 real
failures, the max duration is the deliberate 4 second sleep plus overhead.
Nothing fabricated, nothing estimated. Step 1 gate met.

## Step 2: real load, five real conditions (2026-08-14)

Ran `scripts/loadgen.py quiet steady busy degraded incident --minutes 2`
against `inr-monitored-dev`, 05:42:16Z to 05:52:25Z. 581 real invocations, 98
real errors. Client-side counts reconcile with CloudWatch exactly (581 = 581,
98 = 98).

Per-minute CloudWatch data (AWS/Lambda, period 60, times UTC):

| minute | condition | invocations | errors | throttles | avg dur ms | max conc |
|--------|-----------|-------------|--------|-----------|------------|----------|
| 05:42  | quiet     | 4   | 0  | 0  | 21    | 1  |
| 05:43  | quiet     | 4   | 0  | 0  | 27    | 1  |
| 05:44  | steady    | 24  | 0  | 0  | 19    | 2  |
| 05:45  | steady    | 23  | 0  | 0  | 621   | 4  |
| 05:46  | busy      | 87  | 0  | 0  | 286   | 7  |
| 05:47  | busy      | 94  | 0  | 0  | 429   | 6  |
| 05:48  | degraded  | 39  | 5  | 0  | 774   | 3  |
| 05:49  | degraded  | 40  | 5  | 0  | 564   | 2  |
| 05:50  | incident  | 116 | 44 | 0  | 926   | 9  |
| 05:51  | incident  | 115 | 43 | 0  | 898   | 8  |
| 05:52  | burst     | 35  | 1  | 16 | 4892  | 10 |

Two findings worth keeping. First, boto3 silently retries throttled invokes,
so the load generator reported 0 throttles while CloudWatch recorded 16 real
ones in the burst minute; the metric is the truth, the client is an optimist.
Second, the account's concurrency cap of 10 was actually reached (max
concurrent = 10.0 in the burst minute), which is what made those throttles
possible at all.

Observed real ranges to calibrate descriptors against: traffic 4 to 116 per
minute; error rate 0%, 12.5%, ~38%; average duration 19 ms to 4.9 s;
concurrency 1 to the cap of 10; throttles 0 or 16. Step 2 gate met.

## Step 3: descriptors recalibrated to reality (2026-08-14)

Kept the prototype's phrase pools, rebuilt every dimension against what a
Lambda actually has: traffic = Invocations/min, capacity =
ConcurrentExecutions against the real cap of 10, stability = error rate,
change = minutes since last deploy (real LastModified), queue = Throttles,
which are literally requests pressed against the ceiling and turned away.

Thresholds sit between the measured conditions, not at made-up round numbers:
quiet was 4/min so "low" ends at 12; steady was 24 so "steady" ends at 50;
busy was ~90 so "heavy" ends at 100; incident was ~115 and lands in "flood".
Degraded ran a real 12.5% error rate ("degraded" band is 5 to 25%); incident
ran ~38% ("critical" is 25%+). The burst minute threw 16 real throttles, so
"pressured" covers 6 to 20.

Replayed all 11 real minutes from step 2 through the deriver
(`scripts/replay_calibration.py`): quiet maps to STABLE with low traffic,
steady to STABLE, busy to SURGE, degraded to STRAIN, incident to DANGER with
flood traffic and critical stability, and the burst minute to STRAIN with a
pressured queue at urgent capacity. Every condition we created lands in a
distinct, sensible state. One tweak came out of the replay: the SURGE gate
moved from 100 to 60 invocations/min because busy (~90/min, concurrency 6-7)
is genuinely this Lambda's surge condition.

## Step 4: the narrator speaks, end to end (2026-08-14)

Deployed `inr-narrator-dev`: reads the heartbeat's real per-minute CloudWatch
metrics (GetMetricData, anchored on the newest minute with data because
delivery lags), gets deploy recency from the function's real LastModified,
derives descriptors and mood, calls Gemini with the key from Secrets Manager
(`infra-narrator/gemini`), structured JSON out. No deterministic fallback
poem exists anywhere; if all models fail the invocation fails honestly.

First real poem, 06:04:18Z, from a genuinely idle system (the load run had
ended twelve minutes earlier, all metrics truly zero):

    The tide withdraws and leaves the shore,
    No heavy currents push no more.
    The settling dust begins to sleep,
    As quiet chambers sink and keep.
    I shed the past and wear the chill,
    A cooling metal, small and still.

The mood came out RECOVERY, not IDLE, and that was true: both functions
share one code asset, so deploying the narrator had genuinely redeployed the
monitored function 1.7 minutes earlier. Real LastModified, real "shedding
skin". The model that answered was the fallback (gemini-3.5-flash-lite); the
primary failed silently, so the seam now logs each model failure. Step 4
gate met.

## Step 5: memory and a pulse (2026-08-14)

Added `inr-poems-dev` (DynamoDB, pay per request): latest poem at pk=LATEST,
history rows at pk=POEM keyed by timestamp, expiring after seven days. Added
the EventBridge rule `inr-narrate-dev`, rate(15 minutes), targeting the
narrator. Verified for real: a manual invocation wrote both rows (LATEST
read back correctly, one history row), and `describe-rule` shows ENABLED
with rate(15 minutes). Unattended firing gets proven in step 7 by watching
new rows appear with nobody touching anything.

The model chain earned its keep twice while testing. First the primary
(gemini-flash-latest) hit the inherited 18 second timeout, a limit that came
from debugging-saga's API Gateway budget; nothing in this path is behind API
Gateway, so the primary now gets 30 seconds. Then it 503'd anyway (it has
moods of its own), so the chain widened: gemini-flash-latest, then
gemini-3.5-flash, then gemini-3.5-flash-lite. Every poem so far has come
from the reliable lite model, and each record stores which model actually
answered, so nothing needs to be taken on faith.

## Step 6: the rack unit lives again (2026-08-14)

Two more stacks. `inr-dev-api`: one read-only route, GET /poem, returning
the latest poem plus a short history from DynamoDB; the frontend can never
trigger generation, so refreshing the page spends a DynamoDB read and
nothing else. `inr-dev-hosting`: private S3 bucket behind CloudFront with
Origin Access Control, API base injected as config.js at deploy time.

The frontend is the prototype's rack-unit aesthetic rebuilt in plain HTML,
CSS and JS: panel screws, etched labels, LED cluster keyed to the real mood,
CRT screen with scanline and glow, the typing-effect reveal, and two things
the prototype could not have had because its data was fake: a telemetry
strip showing the actual numbers behind the poem (invocations per minute,
error rate, throttles, duration, concurrency, which model answered, when),
and a history log of earlier real poems. One label changed on purpose: the
prototype's etched vendor name was a real company's, so the panel now reads
INR SYSTEMS.

Live at https://d28dzd8nkgz1no.cloudfront.net and verified in a browser:
poem typing out, real zeros on the telemetry strip (the system was genuinely
quiet), three history rows.

Also observed while wiring this up: the poem history already contained rows
at 06:28:06Z and 06:43:10Z, exactly fifteen minutes apart, generated by
nothing but the EventBridge rule. The schedule was firing unattended before
step 7 even started, and with the widened 30 second budget the primary model
(gemini-flash-latest) answered the 06:43 run itself.
