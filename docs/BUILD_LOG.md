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
