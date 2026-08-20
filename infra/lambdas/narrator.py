"""The narrator: reads the heartbeat's real CloudWatch metrics, derives
metaphor descriptors, asks the model for a poem, and (when a table is
configured) stores it for the frontend.

Runs on an EventBridge schedule. Everything upstream of the poem is
measured: invocations, errors, throttles, duration and concurrency come
from CloudWatch, deploy recency from the function's real LastModified.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from descriptors import derive, derive_mood
from poem_model import PoemError, generate_poem, voice_stage_for

MONITORED_FUNCTION = os.environ.get("MONITORED_FUNCTION", "inr-monitored-dev")
WINDOW_MIN = int(os.environ.get("WINDOW_MIN", "5"))
TABLE_NAME = os.environ.get("TABLE_NAME", "")
HISTORY_KEEP_DAYS = 7
VOICE_HISTORY_LOOKBACK = 6
STOPWORDS = {
    "the", "and", "with", "that", "this", "from", "have", "your", "into",
    "still", "even", "than", "what", "when", "where", "here", "there",
    "while", "through", "beneath", "within", "without", "does", "are",
    "was", "were", "been", "being",
}


def _metric_query(qid, metric, stat):
    return {
        "Id": qid,
        "MetricStat": {
            "Metric": {
                "Namespace": "AWS/Lambda",
                "MetricName": metric,
                "Dimensions": [{"Name": "FunctionName",
                                "Value": MONITORED_FUNCTION}],
            },
            "Period": 60,
            "Stat": stat,
        },
        "ReturnData": True,
    }


def read_metrics(now=None):
    """Pull real per-minute metrics and reduce them to the deriver's input.

    Anchors the window on the newest minute that actually has data, because
    CloudWatch delivery lags a minute or two behind reality.
    """
    cw = boto3.client("cloudwatch")
    now = now or datetime.now(timezone.utc)
    end = now.replace(second=0, microsecond=0)
    start = end - timedelta(minutes=WINDOW_MIN + 3)

    resp = cw.get_metric_data(
        StartTime=start, EndTime=end, ScanBy="TimestampAscending",
        MetricDataQueries=[
            _metric_query("inv", "Invocations", "Sum"),
            _metric_query("err", "Errors", "Sum"),
            _metric_query("thr", "Throttles", "Sum"),
            _metric_query("dur", "Duration", "Average"),
            _metric_query("conc", "ConcurrentExecutions", "Maximum"),
        ])

    series = {}
    for r in resp["MetricDataResults"]:
        series[r["Id"]] = dict(zip(r["Timestamps"], r["Values"]))

    stamps = sorted(set().union(*[s.keys() for s in series.values()] or [set()]))
    if not stamps:
        return {"invocations_per_min": 0.0, "error_rate": 0.0,
                "max_concurrent": 0.0, "throttles": 0.0,
                "avg_duration_ms": 0.0, "window_min": WINDOW_MIN,
                "window_end": end.isoformat(timespec="seconds")}

    anchor = stamps[-1]
    window = [anchor - timedelta(minutes=i) for i in range(WINDOW_MIN)]

    inv = sum(series["inv"].get(t, 0.0) for t in window)
    err = sum(series["err"].get(t, 0.0) for t in window)
    thr = sum(series["thr"].get(t, 0.0) for t in window)
    conc = max((series["conc"].get(t, 0.0) for t in window), default=0.0)
    # invocation-weighted mean of the per-minute averages
    dur_num = sum(series["dur"].get(t, 0.0) * series["inv"].get(t, 0.0)
                  for t in window)
    dur = dur_num / inv if inv else 0.0

    return {
        "invocations_per_min": inv / WINDOW_MIN,
        "error_rate": err / inv if inv else 0.0,
        "max_concurrent": conc,
        "throttles": thr,
        "avg_duration_ms": round(dur, 2),
        "window_min": WINDOW_MIN,
        "window_end": anchor.isoformat(timespec="seconds"),
    }


def minutes_since_deploy():
    cfg = boto3.client("lambda").get_function_configuration(
        FunctionName=MONITORED_FUNCTION)
    last = datetime.strptime(cfg["LastModified"], "%Y-%m-%dT%H:%M:%S.%f%z")
    return (datetime.now(timezone.utc) - last).total_seconds() / 60.0


def recent_words(table, limit=VOICE_HISTORY_LOOKBACK):
    """Distinctive words from the machine's own last few real poems.

    Real history in, nothing invented: only used to steer the model away
    from imagery it has already spent recently.
    """
    if not table:
        return []
    items = table.query(
        KeyConditionExpression=Key("pk").eq("POEM"),
        ScanIndexForward=False,
        Limit=limit,
    )["Items"]
    words = Counter()
    for item in items:
        poem = json.loads(item["body"]).get("poem", "")
        for w in re.findall(r"[a-zA-Z']+", poem.lower()):
            if len(w) > 4 and w not in STOPWORDS:
                words[w] += 1
    return [w for w, _ in words.most_common(8)]


def bump_voice_count(table):
    """Atomically increments the real, un-TTL'd count of poems ever written.

    Called only after a poem is actually written, so the count never counts
    a failed attempt. Returns the new total.
    """
    if not table:
        return 0
    resp = table.update_item(
        Key={"pk": "META", "sk": "VOICE"},
        UpdateExpression="ADD poem_count :inc",
        ExpressionAttributeValues={":inc": 1},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["poem_count"])


def store(record):
    if not TABLE_NAME:
        return
    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    expires = int((datetime.now(timezone.utc)
                   + timedelta(days=HISTORY_KEEP_DAYS)).timestamp())
    item = {"pk": "POEM", "sk": record["generated_at"], "expires_at": expires,
            "body": json.dumps(record)}
    table.put_item(Item=item)
    table.put_item(Item={"pk": "LATEST", "sk": "LATEST",
                         "body": json.dumps(record)})


def handler(event, context):
    metrics = read_metrics()
    metrics["minutes_since_deploy"] = round(minutes_since_deploy(), 1)

    derived = derive(metrics)
    mood = derive_mood(metrics)

    table = boto3.resource("dynamodb").Table(TABLE_NAME) if TABLE_NAME else None
    # Real history in: how many times has this machine actually spoken
    # before, and what did it just say. Only used to steer the next poem,
    # never to invent facts about the system.
    prior_count = 0
    words = []
    if table:
        meta = table.get_item(Key={"pk": "META", "sk": "VOICE"}).get("Item")
        prior_count = int(meta["poem_count"]) if meta else 0
        words = recent_words(table)
    voice_stage = voice_stage_for(prior_count + 1)

    try:
        result = generate_poem(mood, derived,
                                voice={"stage": voice_stage, "avoid_words": words})
    except PoemError as exc:
        # No poem is better than a fake poem. Fail loudly for the schedule's
        # error metric and leave the last real poem in place for readers.
        raise RuntimeError(f"poem generation failed: {exc}") from exc

    # Only a genuinely written poem increments the count.
    poem_count = bump_voice_count(table) if table else prior_count + 1

    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mood": mood,
        "metrics": metrics,
        "levels": derived["levels"],
        "descriptors": {k: derived[k] for k in
                        ("traffic_behavior", "scaling_behavior",
                         "error_condition", "deployment_activity",
                         "queue_condition")},
        "poem": result["poem"],
        "model": result["model"],
        "subject": MONITORED_FUNCTION,
        "voice_stage": voice_stage,
        "poem_count": poem_count,
    }
    store(record)
    return record
