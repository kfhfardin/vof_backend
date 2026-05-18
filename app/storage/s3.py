"""S3-compatible object store (aiobotocore).

Works against AWS S3, Cloudflare R2, and MinIO. The endpoint is configured
via S3_ENDPOINT_URL: empty for real S3, set for R2/MinIO.

The aiobotocore client is created **once per S3ObjectStore instance** and
reused for every put/get/delete/signed_url call. The previous pattern of
opening a fresh client per call paid TLS handshake + auth setup on every
call — that's on the hot path for intake uploads and post-call artifact
saves. Lifespan shutdown calls close() to drain the connection pool.
"""

from __future__ import annotations

import asyncio
from typing import Any, BinaryIO, Literal

from aiobotocore.session import get_session
from botocore.client import Config  # type: ignore[import-untyped]

from app.settings import get_settings


class S3ObjectStore:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint_url or None
        self._region = settings.s3_region
        self._access_key = settings.s3_access_key.get_secret_value()
        self._secret_key = settings.s3_secret_key.get_secret_value()
        self._client: Any = None
        self._client_cm: Any = None
        self._init_lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._init_lock:
            if self._client is not None:
                return self._client
            session = get_session()
            self._client_cm = session.create_client(
                "s3",
                endpoint_url=self._endpoint,
                region_name=self._region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=Config(signature_version="s3v4"),
            )
            self._client = await self._client_cm.__aenter__()
        return self._client

    async def close(self) -> None:
        """Drain the aiobotocore client. Called from FastAPI lifespan shutdown."""
        if self._client_cm is not None:
            await self._client_cm.__aexit__(None, None, None)
            self._client_cm = None
            self._client = None

    async def put(self, key: str, data: BinaryIO | bytes, content_type: str) -> str:
        body = data.read() if hasattr(data, "read") else data
        c = await self._get_client()
        await c.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=content_type)
        return key

    async def get(self, key: str) -> bytes:
        c = await self._get_client()
        resp = await c.get_object(Bucket=self._bucket, Key=key)
        async with resp["Body"] as stream:
            return await stream.read()  # type: ignore[no-any-return]

    async def delete(self, key: str) -> None:
        c = await self._get_client()
        await c.delete_object(Bucket=self._bucket, Key=key)

    async def signed_url(
        self,
        key: str,
        ttl_seconds: int = 900,
        method: Literal["GET", "PUT"] = "GET",
    ) -> str:
        op = "get_object" if method == "GET" else "put_object"
        c = await self._get_client()
        url = await c.generate_presigned_url(
            op,
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_seconds,
            HttpMethod=method,
        )
        return str(url)
