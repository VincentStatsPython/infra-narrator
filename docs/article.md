# Weekend Creative Agent Challenge: Infrastructure Narrator

Tags: #agents

A machine has been writing poetry about its own health, unattended, since last week. Now its voice is maturing while it does it.

## Vision & What the App Does

Last week's challenge was to build a creative app. This week's question is harder: can it run itself? Infrastructure Narrator had half the answer already. A real AWS Lambda function exists purely to be watched. Every fifteen minutes another Lambda reads its real CloudWatch metrics, turns them into metaphor, and asks an AI model to write a short rhyming poem in the first person, the machine describing its own condition. Nobody opens the page to make that happen. It has been happening on a schedule since the moment it deployed.

What was missing was growth. A machine saying the same kind of thing in the same voice forever isn't alive in any interesting sense. It's a cron job with a costume on. So for this challenge the narrator got real memory of itself: a growing count of every poem it has ever written, and a habit of checking which words it used recently so it can reach for different ones. As that count climbs, the voice audibly changes. Plainer and shorter at first. More confident and layered later. Eventually willing to admit, in its own words, that a feeling has happened to it before.

## How You Built It

The count lives at `pk=META, sk=VOICE` in the same DynamoDB table the poems already used. It increments with an atomic `ADD poem_count :1`, and only after a poem is actually written, never before, so a failed generation can't inflate it. It has no TTL on purpose, unlike the 7-day poem history, because the machine's sense of its own age shouldn't reset every week just because the archive does.

Before writing, the narrator now also pulls its own last six stored poems, strips out short and common words, and hands the model a short list of imagery it has recently spent. The count maps to one of three voice stages: waking under 10 poems, finding its voice from 10 to 39, seasoned at 40 and up. Each stage carries its own instruction, folded into the same prompt template that already handled mood and the descriptor blocks. Real numbers still drive the language choices. Nothing about that changed, it just got one layer deeper.

The infrastructure change was small but real. The narrator's DynamoDB grant went from write-only to read-write, because remembering itself means it actually has to read what it wrote.

I didn't want to just promise this worked, so I invoked the narrator directly 40 times over a weekend, the same code path EventBridge calls every fifteen minutes, and kept every result. Poem 1 is plain: "I do not shake, I do not strain, the heavy water leaves no pain." Poem 10 crossed into "finding its voice" and immediately reached for an extended, personified image nobody prompted: "The tide withdraws its pale and drifting hand." Poem 41, the first at "seasoned," did something none of the first ten did. It named its own repetition: "A familiar descent into shadow and snow." I didn't write that line. The model did, because the real count told it, honestly, that it had been here before.

## AWS Services Used / Architecture Overview

Same eight-service, four-stack CDK-TS backbone as last week. AWS Lambda runs the heartbeat, the narrator, and the read API. Amazon CloudWatch is the only source of truth for the machine's condition. Amazon EventBridge runs the fifteen-minute schedule, the thing that actually makes this an agent instead of a demo button. Amazon DynamoDB is now read-write, holding both the poem history and the new voice counter. Amazon API Gateway exposes one read-only `GET /poem`, so a page refresh never spends model quota. S3 and CloudFront serve the frontend, and Secrets Manager holds the model key. Google Gemini writes the poems. This account still carries an unresolved Bedrock throttle and a weekend isn't the timescale support tickets move on, but every AWS piece around the model, including the part that now gives the machine a memory, is real and runs on its own.

## What You Learned

Making something always-on wasn't the hard part. This app already cleared that bar last week. The hard part is making the unattended output worth returning to, which meant giving the schedule something to accumulate instead of something to repeat. A plain, monotonic counter with no TTL turned out to be enough of a real signal to hang real personality drift on, without inventing anything underneath it. And the clearest proof it worked wasn't a metric at all. It was watching poem 41 describe its own deja vu in a sentence I never asked it to write.

## Link to App or Repo

- Live app: https://d28dzd8nkgz1no.cloudfront.net
- Source: https://github.com/VincentStatsPython/infra-narrator
