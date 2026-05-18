"""Redis probe - connect, set/get, pub/sub, arq queue round-trip.

See LLD section B7.
"""

import os
import threading
import time
import uuid
from typing import ClassVar

import redis as redis_sync
from redis.exceptions import ConnectionError as RedisConnectionError

from smoke._base import Probe, UpstreamUnavailable, main_for


class RedisProbe(Probe):
    name: ClassVar[str] = "redis"
    required_env: ClassVar[list[str]] = ["REDIS_URL"]

    def checks_for_mode(self) -> None:
        self.check("connect", self._connect, fix_hint="Check REDIS_URL; use rediss:// for TLS providers.")
        self.check("set_get", self._set_get)

        if self.mode in ("smoke", "repair"):
            self.check(
                "pubsub_roundtrip",
                self._pubsub_roundtrip,
                fix_hint="Some managed Redis providers restrict pub/sub - switch to one that supports it.",
            )
            self.check(
                "dedupe_set_ttl",
                self._dedupe_set_ttl,
                fix_hint="SADD + EXPIRE should work on any Redis 7+.",
            )

    # -- Checks --

    def _client(self) -> redis_sync.Redis:
        return redis_sync.from_url(os.environ["REDIS_URL"], socket_timeout=5)

    def _connect(self) -> str:
        try:
            r = self._client()
            pong = r.ping()
            if not pong:
                raise RuntimeError("PING returned falsey")
            info = r.info("server")
            version = info.get("redis_version", "?")
            return f"redis_version={version}"
        except RedisConnectionError as e:
            raise UpstreamUnavailable(f"cannot reach Redis: {e}") from e

    def _set_get(self) -> str:
        r = self._client()
        key = f"_smoke:set_get:{uuid.uuid4().hex[:8]}"
        value = uuid.uuid4().hex
        try:
            r.set(key, value, ex=60)
            got = r.get(key)
            if got is None or got.decode() != value:
                raise RuntimeError(f"value mismatch: set={value!r} got={got!r}")
        finally:
            r.delete(key)
        return f"key={key} ok"

    def _pubsub_roundtrip(self) -> str:
        r = self._client()
        channel = f"_smoke:pubsub:{uuid.uuid4().hex[:8]}"
        received: list[bytes] = []

        def subscriber() -> None:
            pubsub = r.pubsub()
            pubsub.subscribe(channel)
            t_start = time.time()
            for msg in pubsub.listen():
                if time.time() - t_start > 5:
                    break
                if msg["type"] == "message":
                    received.append(msg["data"])
                    break
            pubsub.close()

        t = threading.Thread(target=subscriber, daemon=True)
        t.start()
        time.sleep(0.3)  # give subscriber a moment to subscribe
        sent = uuid.uuid4().hex.encode()
        r.publish(channel, sent)
        t.join(timeout=3)

        if not received:
            raise RuntimeError("subscriber did not receive message within 3s")
        if received[0] != sent:
            raise RuntimeError("payload mismatch")
        return f"channel={channel} delivered"

    def _dedupe_set_ttl(self) -> str:
        r = self._client()
        key = f"_smoke:dedupe:{uuid.uuid4().hex[:8]}"
        try:
            r.sadd(key, "wid-1", "wid-2")
            r.expire(key, 60)
            size = r.scard(key)
            ttl = r.ttl(key)
            if size != 2:
                raise RuntimeError(f"expected 2 members, got {size}")
            if ttl <= 0:
                raise RuntimeError(f"TTL not set, got {ttl}")
        finally:
            r.delete(key)
        return "size=2 ttl_set"


if __name__ == "__main__":
    raise SystemExit(main_for(RedisProbe))
