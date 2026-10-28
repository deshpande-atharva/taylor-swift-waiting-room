"""
Shared test helpers.

Your handlers read their configuration and create their boto3 clients when they are IMPORTED (the normal Lambda
pattern: warm invocations reuse them). So each test has to
  1. start a moto mock,
  2. create the AWS resources the handler expects,
  3. THEN import the handler fresh.
load_module() does step 3 under a unique module name every time, so nothing leaks between tests.

Add whatever else your option needs (a queue, a second table, environment variables) to the `aws` fixture.
"""
import importlib.util
import itertools
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

REPO = Path(__file__).resolve().parent.parent
LAMBDAS = REPO / "lambdas"

_counter = itertools.count()


def load_module(relative_path: str):
    """Import a Lambda handler file fresh, e.g. load_module("waiting_room/join_handler.py")."""
    path = LAMBDAS / relative_path
    folder = str(path.parent)
    if folder not in sys.path:
        sys.path.insert(0, folder)          # like Lambda: files next to the handler (telemetry.py) can be imported
    name = f"_under_test_{next(_counter)}_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Aws:
    """Handle to the mocked resources, passed to your tests."""


class FakeRedis:
    """In-memory Redis mock that supports the commands our handlers use."""

    def __init__(self, **kwargs):
        self._data = {}
        self._ttls = {}

    def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    def setnx(self, key, value):
        if key not in self._data:
            self._data[key] = value
            return True
        return False

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value
        return True

    def hset(self, key, mapping=None, **kwargs):
        if key not in self._data:
            self._data[key] = {}
        if mapping:
            self._data[key].update(mapping)
        self._data[key].update(kwargs)

    def hgetall(self, key):
        return self._data.get(key, {})

    def hget(self, key, field):
        return self._data.get(key, {}).get(field)

    def expire(self, key, seconds):
        self._ttls[key] = seconds
        return True

    def delete(self, *keys):
        for k in keys:
            self._data.pop(k, None)

    def exists(self, key):
        return 1 if key in self._data else 0

    def eval(self, script, numkeys, *keys_and_args):
        """Execute our join Lua script logic in Python."""
        keys = list(keys_and_args[:numkeys])
        args = list(keys_and_args[numkeys:])
        # Reproduce the atomic join script:
        #   KEYS = [next_position, start_time, last_join_time]
        #   ARGV = [now, gap_threshold]
        last = float(self.get(keys[2]) or "0")
        now = float(args[0])
        gap = float(args[1])
        if (now - last) > gap:
            self.set(keys[0], 0)
            self.delete(keys[1])
        self.set(keys[2], args[0])
        pos = self.incr(keys[0])
        if pos == 1:
            self.set(keys[1], args[0])
        return pos

    def flushall(self):
        self._data.clear()
        self._ttls.clear()


# Singleton so all handlers in one test share the same "Redis"
_fake_redis_instance = None


def _get_fake_redis(**kwargs):
    global _fake_redis_instance
    if _fake_redis_instance is None:
        _fake_redis_instance = FakeRedis()
    return _fake_redis_instance


@pytest.fixture
def aws(monkeypatch):
    """A fresh mocked AWS with an admissions table, Redis mock, and the environment the handlers read."""
    global _fake_redis_instance
    _fake_redis_instance = FakeRedis()  # fresh per test

    with mock_aws():
        for key, value in {
            "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1", "AWS_REGION": "us-east-1",
        }.items():
            monkeypatch.setenv(key, value)

        ddb = boto3.client("dynamodb")
        ddb.create_table(
            TableName="wr-admissions",
            KeySchema=[{"AttributeName": "visitor_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "visitor_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        a = Aws()
        a.ddb = ddb
        a.table = boto3.resource("dynamodb").Table("wr-admissions")
        a.fake_redis = _fake_redis_instance

        for key, value in {
            "ADMISSIONS_TABLE": "wr-admissions",
            "ADMIT_PER_SECOND": "10",
            "POLL_INTERVAL_SECONDS": "5",
            "ADMISSION_VALID_SECONDS": "600",
            "REDIS_HOST": "localhost",
            "REDIS_PORT": "6379",
        }.items():
            monkeypatch.setenv(key, value)

        # Patch redis.Redis so handlers get our FakeRedis instead of a real connection
        import redis as redis_mod
        monkeypatch.setattr(redis_mod, "Redis", _get_fake_redis)

        yield a
