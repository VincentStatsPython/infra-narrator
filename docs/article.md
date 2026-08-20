# Weekend Creative Agent Challenge: Infrastructure Narrator

Tags: #agents

A machine that has been writing poetry about its own health, unattended,
since last week — and now its voice is visibly maturing as it does.

## Vision & What the App Does

Last week's challenge was to build a creative app. This week's asks the
harder question: can it run itself? Infrastructure Narrator already had
half the answer built in. A real AWS Lambda function exists purely to be
watched, and every fifteen minutes another Lambda reads its real CloudWatch
metrics, translates them into metaphor, and asks an AI model to write a
short rhyming poem in the first person — the machine describing its own
condition. Nobody has to open the page for that to happen; it has been
happening on a schedule since the moment it deployed.

What was missing was growth. A machine that says the exact same kind of
thing in the exact same voice, forever, isn't really "alive" in any
interesting sense — it's a cron job with a costume. So for this challenge
the narrator gained real memory of itself: a genuine, ever-growing count of
every poem it has ever written, and a habit of glancing back at the words
it used most recently so it can reach for different ones. As that count
climbs, its voice audibly changes — plainer and shorter at first, more
confident and layered later, eventually willing to admit, in its own words,
that a feeling has happened to it before.

## How You Built It

The count lives at `pk=META, sk=VOICE` in the same DynamoDB table the poems
already used, incremented by an atomic `ADD poem_count :1` — but only
*after* a poem is actually written, never before, so a failed generation
can't inflate it. It deliberately has no TTL, unlike the 7-day poem history,
so the machine's sense of its own age doesn't reset every week.

Before writing, the narrator now also queries its own last six real stored
poems, strips out short and common words, and hands the model a short list
of imagery it has recently spent. The count maps to one of three voice
stages — waking (under 10 poems), finding its voice (10-39), seasoned (40
and up) — each with its own instruction folded into the same prompt
template that already carried the mood and descriptor blocks, so the
calibration philosophy stays consistent: real numbers drive real language
choices, nothing is invented.

The only infrastructure change was small but real: the narrator's DynamoDB
grant went from write-only to read-write, because "remembering itself"
means it actually has to read what it wrote.

To prove it inside a weekend rather than promise it, I invoked the narrator
directly 40 times (the same code path EventBridge calls every fifteen
minutes) and kept every result. Poem 1, waking, is plain: "I do not shake,
I do not strain, / The heavy water leaves no pain." Poem 10, the instant it
crossed into "finding its voice," reached unprompted for an extended,
personified image: "The tide withdraws its pale and drifting hand." Poem
41, the first at "seasoned," did something none of the first ten did — it
named its own repetition: "A familiar descent into shadow and snow." I
didn't write that line. The model did, because the real count told it,
truthfully, that it had been here before.

## AWS Services Used / Architecture Overview

Same eight-service, four-stack CDK-TS backbone as last week: AWS Lambda
(heartbeat, narrator, read API), Amazon CloudWatch (the only source of
truth for the machine's condition), Amazon EventBridge (the fifteen-minute
schedule that makes this an agent and not a demo button), Amazon DynamoDB
(now read-write, holding both poem history and the new voice counter),
Amazon API Gateway (one read-only `GET /poem`, so a page refresh never
spends model quota), Amazon S3 + Amazon CloudFront (the frontend), and AWS
Secrets Manager (the model key). Google Gemini remains the model behind the
poems — this account still carries an unresolved Bedrock throttle, and a
weekend isn't the timescale support tickets move on — but every AWS piece
around it, including the part that now gives the machine a memory, is real
and unattended.

## What You Learned

Making something "always-on" isn't the interesting bar to clear — this app
already cleared it last week. The interesting bar is making the unattended
output worth returning to, which meant giving the schedule something to
accumulate rather than just repeat. A genuinely monotonic, un-TTL'd counter
turned out to be enough of a real signal to hang real personality drift on,
without inventing anything. And the clearest proof that it worked wasn't a
metric at all — it was watching poem 41 describe its own déjà vu in a
sentence I never asked it to write.

## Link to App or Repo

- Live app: https://d28dzd8nkgz1no.cloudfront.net
- Source: https://github.com/VincentStatsPython/infra-narrator
