# Weekend Creative Challenge: Infrastructure Narrator

A machine that writes poetry about its own health.

## Vision & What the App Does

Monitoring dashboards tell you what a system is doing. I wanted one that
tells you how the system feels.

Infrastructure Narrator is a small serverless installation where a real AWS
Lambda function is watched by real Amazon CloudWatch metrics, and every
fifteen minutes another Lambda reads those metrics and asks an AI model to
write a short rhyming poem in the first person, as the machine describing
its own condition. The poem lands on a web page styled like a rack-mounted
hardware unit: panel screws, etched labels, a green CRT screen, a status LED
that goes amber when the machine is genuinely struggling, and a typing
effect as the new poem arrives.

The creative trick is a translation layer I call the descriptor pool. Raw
numbers never reach the model. Instead, each metric is mapped into metaphor
language first: traffic becomes tides and wind, errors become fractures and
sparks, throttled requests become rising water, a fresh deployment becomes
shedding skin. The model is then told to inhabit those images, not report
them. When the system was quiet after its first deploy, it wrote:

    The tide withdraws and leaves the shore,
    No heavy currents push no more.
    The settling dust begins to sleep,
    As quiet chambers sink and keep.
    I shed the past and wear the chill,
    A cooling metal, small and still.

Every line of that is backed by a real number. The tide withdrew because
invocations per minute were actually 0.0. It shed the past because the
function had genuinely been redeployed 1.7 minutes earlier.

## How You Built It

I had an old prototype of this idea, and the honest thing to say is that
most of it was fake. It generated "system state" with Math.random() and
called a model straight from client-side React. Two things in it were worth
keeping: the descriptor pool concept and the rack-unit look. Everything else
got rebuilt for real, with one rule: CloudWatch never sees a fabricated
number. We choose what real conditions to create, never what numbers to
report.

Step one was deploying a tiny "monitored" Lambda whose entire job is to
exist and be observed. It does a pinch of arithmetic, sleeps when asked, and
raises a real RuntimeError when asked. My first deploy failed immediately:
my account's total Lambda concurrency cap is 10, so CloudFormation refused
the reserved concurrency I wanted. That constraint turned out to be a gift.
A burst of 25 concurrent slow invocations genuinely hits the ceiling, and
CloudWatch records genuine Throttles.

Step two was a load generator that sends real traffic at chosen rates:
quiet (4/min), steady (24/min), busy (90/min), degraded (40/min with 15
percent deliberate errors), and incident (120/min with 40 percent errors
plus that throttle burst). One surprise from this phase: my script reported
zero throttles while CloudWatch recorded sixteen, because boto3 silently
retries throttled invokes. The client is an optimist; the metric is the
truth.

Step three calibrated the descriptor thresholds against those measured
ranges instead of made-up round numbers, and I replayed all eleven real
minutes of load data through the deriver to check that every condition I
had created landed in a distinct state.

Then came the narrator Lambda, and with it the usual model wrangling. My
primary model timed out on a limit I had copied from an older project, then
returned 503 once I fixed that, so the seam now runs a three-model fallback
chain and every stored poem records which model actually answered. Nothing
is taken on faith, and there is no canned fallback poem anywhere. If every
model fails, the run fails loudly and the page keeps showing the last real
poem.

The part I care most about: the schedule is the author. EventBridge fires
the narrator every fifteen minutes whether or not anyone is watching. While
I was still building the frontend, rows started appearing in DynamoDB
exactly fifteen minutes apart that no human had triggered. Later I ran four
minutes of degraded load, walked away, and the 06:58 scheduled run found a
13.1 percent real error rate on its own and wrote "my stuttering rhythm
sparks and seeks its beat."

For the finale I wanted the machine to survive something worse, so I ran
four minutes of incident-grade load (505 real requests, 177 of them
deliberately failing, plus a concurrency burst) and again touched nothing
else. The 07:13 scheduled run discovered a 36.5 percent error rate,
concurrency pinned at the account cap of 10, and eight real throttles, went
to DANGER, and wrote:

    A heavy gale sweeps through my bone,
    While rising waters press the stone.
    A fracture runs through quiet ground,
    Yet still I stand without a sound.
    My chambers stretch beneath the tide,
    Holding the roaring weight inside.

"Rising waters press the stone" is the descriptor pool doing its job: those
are the eight throttled requests, real ones, that CloudWatch counted when
the burst hit the concurrency ceiling.

## AWS Services Used / Architecture Overview

Eight services, all deployed with AWS CDK in four stacks:

- AWS Lambda, three functions: the monitored heartbeat (the subject), the
  narrator (reads metrics, derives descriptors, calls the model, stores the
  poem), and a read-only API handler
- Amazon CloudWatch: the single source of truth for invocations, errors,
  duration, throttles and concurrency
- Amazon EventBridge: fires the narrator every fifteen minutes, unattended
- Amazon DynamoDB: latest poem plus a week of history, TTL cleaned
- Amazon API Gateway: one read-only GET /poem route, so the frontend can
  never spend model quota no matter how hard anyone refreshes
- Amazon S3 + Amazon CloudFront: host the rack-unit frontend
- AWS Secrets Manager: holds the model API key, read server-side only

The poems come from Google Gemini rather than Amazon Bedrock, and I want to
be straightforward about why: my account currently has an unresolved
account-level Bedrock throttle, and a weekend is not the timescale on which
support tickets resolve. The AI call happens server-side in the narrator
Lambda either way, and everything around it is AWS end to end.

## What You Learned

The metric is the truth and the client is an optimist: boto3 hid real
throttles from me that CloudWatch faithfully recorded. Account-level
constraints can be features: a concurrency cap of 10 is exactly what makes
real throttling demonstrable on a hobby account. Anchoring metric windows
matters: CloudWatch delivery lags a minute or two, so the narrator anchors
its five-minute window on the newest minute that actually has data. And
constraints breed better creative output: calibrating metaphor thresholds
to measured ranges made the poems noticeably more truthful, because a small
Lambda's "flood" is 116 requests a minute, not a production system's
hundred thousand.

Mostly, though: making the machine the author changes the feeling of the
thing. Because EventBridge writes the poems whether or not anyone is
watching, visiting the page feels like checking in on something that has
been quietly keeping a diary. That was the goal.

## Link to App or Repo

- Live app: https://d28dzd8nkgz1no.cloudfront.net
- Source: REPO_URL_PLACEHOLDER
