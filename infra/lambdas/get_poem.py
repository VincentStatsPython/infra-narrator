"""Read endpoint for the frontend: the latest poem plus a short history.

Read-only by design. The frontend never triggers generation; EventBridge
owns the schedule, so a page refresh costs one DynamoDB read and nothing
else.
"""

import json
import os

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ["TABLE_NAME"]
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "12"))

_table = boto3.resource("dynamodb").Table(TABLE_NAME)


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    latest = _table.get_item(Key={"pk": "LATEST", "sk": "LATEST"}).get("Item")
    history = _table.query(
        KeyConditionExpression=Key("pk").eq("POEM"),
        ScanIndexForward=False,
        Limit=HISTORY_LIMIT,
    )["Items"]

    return _resp(200, {
        "latest": json.loads(latest["body"]) if latest else None,
        "history": [json.loads(i["body"]) for i in history],
    })
