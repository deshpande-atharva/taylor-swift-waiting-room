"""
JOIN  (POST /waiting-room/join)  -  Option C: Redis
====================================================
Assigns each visitor a sequential queue position via Redis INCR.
Also records the start time so CheckStatus can compute how many
visitors should be admitted based on elapsed time.

Uses an atomic Lua script to detect a gap between runs (e.g. rehearsal
then stampede) and reset the counters. If more than 60 seconds have
passed since the last join, the position counter and start time are
reset so the new run gets a fresh line.

Redis keys:
    wr:next_position       integer, incremented by each join
    wr:start_time          float epoch, set on first join of each run
    wr:last_join_time      float epoch, updated on every join
    wr:visitor:{id}        hash: queue_position, joined_at
"""
import json
import os
import time
import uuid

import redis
import telemetry

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
GAP_THRESHOLD = 60  # seconds of inactivity before resetting for a new run

r = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT,
    decode_responses=True,
    socket_timeout=5, socket_connect_timeout=5,
)

# Atomic Lua script: reset-on-gap + assign position.
# KEYS[1] = wr:next_position, KEYS[2] = wr:start_time, KEYS[3] = wr:last_join_time
# ARGV[1] = current time, ARGV[2] = gap threshold
_JOIN_SCRIPT = """
local last = tonumber(redis.call('GET', KEYS[3]) or '0')
local now  = tonumber(ARGV[1])
local gap  = tonumber(ARGV[2])
if (now - last) > gap then
    redis.call('SET', KEYS[1], 0)
    redis.call('DEL', KEYS[2])
end
redis.call('SET', KEYS[3], ARGV[1])
local pos = redis.call('INCR', KEYS[1])
if pos == 1 then
    redis.call('SET', KEYS[2], ARGV[1])
end
return pos
"""


def lambda_handler(event, context):
    visitor_id = str(uuid.uuid4())
    now = time.time()

    try:
        position = int(r.eval(
            _JOIN_SCRIPT, 3,
            "wr:next_position", "wr:start_time", "wr:last_join_time",
            str(now), str(GAP_THRESHOLD),
        ))

        r.hset(f"wr:visitor:{visitor_id}", mapping={
            "queue_position": str(position),
            "joined_at": str(now),
        })
        r.expire(f"wr:visitor:{visitor_id}", 3600)
    except redis.RedisError as e:
        return _response(503, {
            "error": "queue_unavailable",
            "message": f"Could not join the line: {e}",
        })

    telemetry.joined()

    return _response(202, {
        "visitor_id": visitor_id,
        "status": "waiting",
        "queue_position": position,
        "poll_interval_seconds": POLL_INTERVAL,
        "poll_path": f"/waiting-room/status/{visitor_id}",
    })


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
