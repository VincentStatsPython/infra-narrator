# Architecture

Four CDK stacks: `inr-dev-monitored` (the subject), `inr-dev-narrator` (the
observer + memory), `inr-dev-api` (read-only), `inr-dev-hosting` (the
panel). The interesting part isn't the stack count, it's the loop: a
Lambda watches another Lambda, and increasingly, watches its own past.

```mermaid
flowchart TD
    subgraph subject["The subject"]
        H[Heartbeat Lambda\ninr-monitored-dev]
    end

    H -- real invocations, errors,\nthrottles, duration, concurrency --> CW[(CloudWatch Metrics)]

    EB[EventBridge\nrate: 15 min] --> N[Narrator Lambda]
    CW -- GetMetricData --> N
    N -- GetFunctionConfiguration\n(real deploy age) --> H

    N --> D[derive metrics]
    D --> DESC[descriptor pool\nnumbers -> imagery phrases]

    subgraph memory["Its own memory"]
        META[(pk=META sk=VOICE\nreal poem count, no TTL)]
        HIST[(pk=POEM history\nlast 6 real poems)]
    end

    N -- read count, read recent words --> META
    N -- read recent imagery --> HIST
    META --> STAGE[voice stage:\nwaking / finding its voice / seasoned]

    DESC --> PROMPT[prompt: mood + descriptors\n+ voice stage + avoid-words]
    STAGE --> PROMPT
    PROMPT --> GEM[Gemini\nflash-latest -> 3.5-flash -> 3.5-flash-lite]
    GEM --> POEM[the poem]

    POEM --> WRITE[(DynamoDB inr-poems-dev\npk=POEM history, pk=LATEST,\npk=META counter bump)]
    WRITE -.grows the memory\nfor next time.-> META

    API[API Gateway\nGET /poem, POST /simulate] --> WRITE
    WEB[CRT panel\nS3 + CloudFront] --> API
```

## Why this shape

- **The schedule is the author.** EventBridge, not a page load, decides
  when the machine speaks. The frontend only ever reads.
- **Memory is a separate, un-TTL'd counter.** The 7-day poem history exists
  for the frontend's "recent history" strip and can safely expire; the
  voice's sense of its own age must not reset with it, so `pk=META` never
  gets a TTL.
- **One read grant, added late.** The narrator originally only had write
  access to its own table (`grantWriteData`). Reading its own memory
  required widening that to `grantReadWriteData` - a real, one-line
  permission change, not a redesign.
- **`/simulate` is fenced separately.** It's the one route that can spend
  model quota on a visitor's click, so it gets its own cooldown and its
  own `pk=SIM` namespace, kept entirely out of the real history and out of
  the voice's memory of itself.

## AWS services in play

Lambda (heartbeat, narrator, read API, simulate), CloudWatch (the only
source of truth about the heartbeat's condition), EventBridge (the 15-min
schedule), DynamoDB (poems + voice memory), API Gateway (read + simulate),
Secrets Manager (the Gemini key), S3 + CloudFront (the panel).
