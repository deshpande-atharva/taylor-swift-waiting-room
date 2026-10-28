"""
Tests for Option C (Redis) waiting room.

Covers:
  - Join: returns 202, correct fields, sequential positions
  - Status: waiting, admitted, order_placed, malformed id
  - Admission record: matches the gate's contract
  - Single-use: token shown until used, then hidden
  - Concurrent joins get different positions
  - Concurrent status polls for the same visitor don't double-admit
"""
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from conftest import load_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _body(response):
    return json.loads(response["body"])


def _join(join_mod):
    return join_mod.lambda_handler({}, None)


def _status(status_mod, visitor_id):
    return status_mod.lambda_handler(
        {"pathParameters": {"visitor_id": visitor_id}}, None,
    )


# ---------------------------------------------------------------------------
# Join tests
# ---------------------------------------------------------------------------

class TestJoin:
    def test_returns_202_with_required_fields(self, aws):
        join = load_module("waiting_room/join_handler.py")
        resp = _join(join)
        assert resp["statusCode"] == 202
        body = _body(resp)
        assert body["status"] == "waiting"
        assert "visitor_id" in body
        # visitor_id must be a valid UUID
        uuid.UUID(body["visitor_id"])
        assert "poll_interval_seconds" in body
        assert "poll_path" in body
        assert body["poll_path"].startswith("/waiting-room/status/")

    def test_sequential_positions(self, aws):
        join = load_module("waiting_room/join_handler.py")
        positions = [_body(_join(join))["queue_position"] for _ in range(5)]
        assert positions == [1, 2, 3, 4, 5]

    def test_unique_visitor_ids(self, aws):
        join = load_module("waiting_room/join_handler.py")
        ids = [_body(_join(join))["visitor_id"] for _ in range(10)]
        assert len(set(ids)) == 10

    def test_concurrent_joins_get_different_positions(self, aws):
        """Multiple joins at the same instant must each get a unique position."""
        join = load_module("waiting_room/join_handler.py")

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_join, join) for _ in range(5)]
            results = [_body(f.result()) for f in futures]

        positions = [r["queue_position"] for r in results]
        assert len(set(positions)) == 5, f"duplicate positions: {positions}"


# ---------------------------------------------------------------------------
# Status tests
# ---------------------------------------------------------------------------

class TestStatus:
    def test_malformed_id_returns_400(self, aws):
        status = load_module("waiting_room/status_handler.py")
        resp = _status(status, "not-a-uuid")
        assert resp["statusCode"] == 400

    def test_unknown_visitor_returns_400(self, aws):
        status = load_module("waiting_room/status_handler.py")
        resp = _status(status, str(uuid.uuid4()))
        assert resp["statusCode"] == 400

    def test_waiting_when_not_yet_admitted(self, aws):
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        # Join 100 visitors so our visitor is far back in line
        for _ in range(99):
            _join(join)
        resp = _join(join)  # position 100
        vid = _body(resp)["visitor_id"]

        # start_time was just set, so elapsed * 10 < 100 => still waiting
        resp = _status(status, vid)
        assert resp["statusCode"] == 200
        assert _body(resp)["status"] == "waiting"

    def test_admitted_when_turn_comes(self, aws):
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        resp = _join(join)  # position 1
        vid = _body(resp)["visitor_id"]

        # Fake time so that enough time has passed for position 1
        # start_time was set at join time. We manipulate it to be in the past.
        aws.fake_redis.set("wr:start_time", str(time.time() - 10))

        resp = _status(status, vid)
        body = _body(resp)
        assert resp["statusCode"] == 200
        assert body["status"] == "admitted"
        assert "admission_token" in body
        assert "expires_at" in body
        uuid.UUID(body["admission_token"])  # must be a valid UUID

    def test_admission_record_matches_gate_contract(self, aws):
        """The DynamoDB record must have the exact fields the gate expects."""
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        vid = _body(_join(join))["visitor_id"]
        aws.fake_redis.set("wr:start_time", str(time.time() - 10))
        resp = _status(status, vid)
        token = _body(resp)["admission_token"]

        item = aws.table.get_item(Key={"visitor_id": vid})["Item"]
        assert item["visitor_id"] == vid
        assert item["admission_token"] == token
        assert item["used"] is False
        assert int(item["expires_at"]) > 0  # DynamoDB returns Decimal; gate compares numerically
        assert "ttl" in item

    def test_re_poll_returns_same_token(self, aws):
        """Polling again after admission returns the same token (idempotent)."""
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        vid = _body(_join(join))["visitor_id"]
        aws.fake_redis.set("wr:start_time", str(time.time() - 10))

        resp1 = _status(status, vid)
        resp2 = _status(status, vid)
        assert _body(resp1)["admission_token"] == _body(resp2)["admission_token"]

    def test_token_hidden_after_use(self, aws):
        """After the gate marks `used=true`, the token must not be returned."""
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        vid = _body(_join(join))["visitor_id"]
        aws.fake_redis.set("wr:start_time", str(time.time() - 10))
        _status(status, vid)  # admit

        # Simulate the gate marking the admission as used
        aws.table.update_item(
            Key={"visitor_id": vid},
            UpdateExpression="SET #u = :t",
            ExpressionAttributeNames={"#u": "used"},
            ExpressionAttributeValues={":t": True},
        )

        resp = _status(status, vid)
        body = _body(resp)
        assert body["status"] == "admitted"
        assert body.get("order_placed") is True
        assert "admission_token" not in body


# ---------------------------------------------------------------------------
# Concurrency / race-condition tests
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_status_polls_same_visitor(self, aws):
        """Two status calls at the same instant for the same visitor must not
        create two admission records or return different tokens."""
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        vid = _body(_join(join))["visitor_id"]
        aws.fake_redis.set("wr:start_time", str(time.time() - 10))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_status, status, vid) for _ in range(2)]
            results = [_body(f.result()) for f in futures]

        tokens = [r["admission_token"] for r in results if "admission_token" in r]
        assert len(set(tokens)) == 1, f"got different tokens: {tokens}"

    def test_fifo_ordering(self, aws):
        """Visitors who join first should be admitted first."""
        join = load_module("waiting_room/join_handler.py")
        status = load_module("waiting_room/status_handler.py")

        visitors = []
        for _ in range(5):
            resp = _join(join)
            visitors.append(_body(resp)["visitor_id"])

        # Set time so only first 3 are admitted (position 1-3)
        aws.fake_redis.set("wr:start_time", str(time.time() - 0.3))  # 0.3s * 10/s = 3 admitted

        admitted = []
        waiting = []
        for vid in visitors:
            resp = _status(status, vid)
            body = _body(resp)
            if body["status"] == "admitted":
                admitted.append(vid)
            else:
                waiting.append(vid)

        assert admitted == visitors[:3]
        assert waiting == visitors[3:]
