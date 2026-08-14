# Infrastructure Narrator

A machine that writes poetry about its own health.

A small dedicated Lambda exists purely to be watched. Real controlled load is
sent at it, quiet trickles, busy bursts, deliberate errors, and Amazon
CloudWatch records what actually happened. On a schedule, a narrator Lambda
reads those real metrics, translates them into metaphor language through a
descriptor pool (traffic becomes tides and wind, errors become fractures and
sparks, queue depth becomes rising water), and asks a model to write a short
rhyming poem in the first person, as the machine speaking about its own
condition. The poem lands in DynamoDB and a rack-unit style frontend displays
it, green CRT text, LEDs, panel screws and all.

Every number CloudWatch sees is real. The system chooses what conditions to
create (real requests at varying rates, some deliberately failing), never
what numbers to report.

## Architecture

- monitored Lambda: near-empty function, exists to emit real CloudWatch
  metrics (invocations, errors, duration, throttles)
- load generator: local script sending real varying traffic, including
  deliberate error triggers
- narrator Lambda: reads CloudWatch metrics, derives descriptors, calls
  Gemini, stores the poem
- EventBridge: fires the narrator on a schedule, unattended
- DynamoDB: latest poem plus short history
- API Gateway: read endpoint for the frontend
- S3 + CloudFront: hosts the rack-unit UI
- Secrets Manager: Gemini API key

## Layout

- `infra/` CDK app (TypeScript) and Lambda source
- `scripts/` load generator and helpers
- `web/` frontend
- `docs/` build log and article
