"""
STATUS  (GET /waiting-room/status/{visitor_id})  -  Option C: Redis
====================================================================
Time-based admission: max_admitted = (now - start_time) * rate.
If the visitor's position <= max_admitted, they are admitted.

On admission:
  1. Write an admission record to DynamoDB (the gate reads this).
  2. Emit telemetry: admitted() and time_in_line(seconds).
  3. Return the token.

On subsequent polls after admission:
  - If the token has been used (order placed), return order_placed=true.
  - Otherwise return the same token again (idempotent).
"""
import json
import os
import time
import uuid as uuid_mod

import boto3
import redis
from botocore.exceptions import ClientError

import telemetry

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
ADMISSIONS_TABLE = os.environ["ADMISSIONS_TABLE"]
ADMIT_PER_SECOND = float(os.environ.get("ADMIT_PER_SECOND", "10"))
ADMISSION_VALID_SECONDS = int(os.environ.get("ADMISSION_VALID_SECONDS", "600"))

r = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT,
    decode_responses=True,
    socket_timeout=5, socket_connect_timeout=5,
)

dynamodb = boto3.resource("dynamodb")
admissions_table = dynamodb.Table(ADMISSIONS_TABLE)


def lambda_handler(event, context):
    visitor_id = (event.get("pathParameters") or {}).get("visitor_id", "")

    # Validate UUID format
    try:
        parsed = uuid_mod.UUID(visitor_id)
        if str(parsed) != visitor_id.lower():
            raise ValueError
    except (ValueError, AttributeError):
        return _response(400, {
            "error": "invalid_visitor_id",
            "message": "visitor_id must be a valid UUID",
        })

    # Check DynamoDB for an existing admission (handles re-polls and post-order)
    try:
        existing = admissions_table.get_item(Key={"visitor_id": visitor_id})
        if "Item" in existing:
            item = existing["Item"]
            if item.get("used"):
                return _response(200, {"status": "admitted", "order_placed": True})
            return _response(200, {
                "status": "admitted",
                "admission_token": item["admission_token"],
                "expires_at": int(item["expires_at"]),
            })
    except ClientError:
        pass  # DynamoDB unreachable -- fall through to Redis check

    # Look up visitor in Redis
    try:
        visitor_data = r.hgetall(f"wr:visitor:{visitor_id}")
    except redis.RedisError:
        return _response(503, {
            "error": "queue_unavailable",
            "message": "Could not check status",
        })

    if not visitor_data:
        return _response(400, {
            "error": "unknown_visitor",
            "message": "Visitor not found. Join first: POST /waiting-room/join",
        })

    position = int(visitor_data["queue_position"])
    joined_at = float(visitor_data["joined_at"])

    # Compute how many should be admitted by now
    try:
        start_time = float(r.get("wr:start_time") or str(time.time()))
    except redis.RedisError:
        return _response(503, {
            "error": "queue_unavailable",
            "message": "Could not check status",
        })

    elapsed = time.time() - start_time
    max_admitted = int(elapsed * ADMIT_PER_SECOND)

    if position > max_admitted:
        return _response(200, {"status": "waiting"})

    # This visitor's turn has come -- write the admission record
    token = str(uuid_mod.uuid4())
    now = int(time.time())
    expires_at = now + ADMISSION_VALID_SECONDS
    ttl = expires_at + 3600  # DynamoDB cleanup well after expiry

    try:
        admissions_table.put_item(
            Item={
                "visitor_id": visitor_id,
                "admission_token": token,
                "used": False,
                "expires_at": expires_at,
                "ttl": ttl,
            },
            ConditionExpression="attribute_not_exists(visitor_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Another concurrent poll already admitted this visitor -- return that record
            try:
                existing = admissions_table.get_item(Key={"visitor_id": visitor_id})
                item = existing["Item"]
                if item.get("used"):
                    return _response(200, {"status": "admitted", "order_placed": True})
                return _response(200, {
                    "status": "admitted",
                    "admission_token": item["admission_token"],
                    "expires_at": int(item["expires_at"]),
                })
            except (ClientError, KeyError):
                return _response(503, {
                    "error": "admission_check_failed",
                    "message": "Could not verify admission",
                })
        return _response(503, {
            "error": "admission_write_failed",
            "message": "Could not write admission",
        })

    time_waited = time.time() - joined_at
    telemetry.admitted()
    telemetry.time_in_line(time_waited)

    return _response(200, {
        "status": "admitted",
        "admission_token": token,
        "expires_at": expires_at,
    })


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
