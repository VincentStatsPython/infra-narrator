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
