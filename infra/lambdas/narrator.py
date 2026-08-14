"""The narrator: reads the heartbeat's real CloudWatch metrics, derives
metaphor descriptors, asks the model for a poem, and (when a table is
configured) stores it for the frontend.

Runs on an EventBridge schedule. Everything upstream of the poem is
measured: invocations, errors, throttles, duration and concurrency come
from CloudWatch, deploy recency from the function's real LastModified.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import boto3

from descriptors import derive, derive_mood
from poem_model import PoemError, generate_poem

MONITORED_FUNCTION = os.environ.get("MONITORED_FUNCTION", "inr-monitored-dev")
WINDOW_MIN = int(os.environ.get("WINDOW_MIN", "5"))
TABLE_NAME = os.environ.get("TABLE_NAME", "")
HISTORY_KEEP_DAYS = 7


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

    try:
        result = generate_poem(mood, derived)
    except PoemError as exc:
        # No poem is better than a fake poem. Fail loudly for the schedule's
        # error metric and leave the last real poem in place for readers.
        raise RuntimeError(f"poem generation failed: {exc}") from exc

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
    }
    store(record)
    return record
