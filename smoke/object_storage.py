"""Object storage probe (S3-compatible: AWS S3, R2, MinIO).

See LLD section B8.
"""

import os
import uuid
from typing import ClassVar

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from smoke._base import Probe, UpstreamUnavailable, main_for


def _client():  # type: ignore[no-untyped-def]
    endpoint = os.environ.get("S3_ENDPOINT_URL") or None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=10),
    )


class ObjectStorageProbe(Probe):
    name: ClassVar[str] = "object_storage"
    required_env: ClassVar[list[str]] = ["S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_REGION"]

    PREFIX = "_smoke_probe"

    def checks_for_mode(self) -> None:
        self.check(
            "bucket_reachable",
            self._bucket_reachable,
            fix_hint="Check bucket exists and IAM allows ListBucket/HeadBucket.",
        )

        if self.mode in ("smoke", "repair"):
            key = f"{self.PREFIX}/{uuid.uuid4().hex}.bin"
            payload = b"smoke-test " + uuid.uuid4().hex.encode()
            try:
                self.check(
                    "put_object",
                    lambda: self._put(key, payload),
                    fix_hint="IAM may lack s3:PutObject on the bucket.",
                )
                self.check(
                    "get_object",
                    lambda: self._get(key, payload),
                    fix_hint="IAM may lack s3:GetObject on the bucket.",
                )
                self.check(
                    "signed_url_generation",
                    lambda: self._signed_url(key),
                    fix_hint="If signed URL returns 403, S3_REGION may not match bucket region.",
                )
                self.check(
                    "workspace_prefix_isolation",
                    self._prefix_isolation,
                    fix_hint="Bucket ACL too permissive - tighten if production data ever lands.",
                )
            finally:
                self.check("delete_object", lambda: self._delete(key))

    # -- Checks --

    def _bucket_reachable(self) -> str:
        try:
            c = _client()
            c.head_bucket(Bucket=os.environ["S3_BUCKET"])
            return f"bucket={os.environ['S3_BUCKET']}"
        except EndpointConnectionError as e:
            raise UpstreamUnavailable(f"cannot reach S3 endpoint: {e}") from e
        except (ClientError, BotoCoreError) as e:
            raise RuntimeError(str(e)) from e

    def _put(self, key: str, payload: bytes) -> str:
        c = _client()
        c.put_object(
            Bucket=os.environ["S3_BUCKET"], Key=key, Body=payload, ContentType="application/octet-stream"
        )
        return f"key={key} bytes={len(payload)}"

    def _get(self, key: str, expected: bytes) -> str:
        c = _client()
        resp = c.get_object(Bucket=os.environ["S3_BUCKET"], Key=key)
        body = resp["Body"].read()
        if body != expected:
            raise RuntimeError(f"payload mismatch: get={len(body)}B expected={len(expected)}B")
        return f"bytes={len(body)} match=true"

    def _signed_url(self, key: str) -> str:
        c = _client()
        url = c.generate_presigned_url(
            "get_object",
            Params={"Bucket": os.environ["S3_BUCKET"], "Key": key},
            ExpiresIn=900,
            HttpMethod="GET",
        )
        if not url.startswith(("http://", "https://")):
            raise RuntimeError(f"unexpected URL form: {url[:50]}")
        return "expires_in=900s"

    def _prefix_isolation(self) -> str:
        c = _client()
        # Put one object under prefix A, list under prefix B, expect empty.
        a_key = f"{self.PREFIX}/iso_a/{uuid.uuid4().hex}.txt"
        b_prefix = f"{self.PREFIX}/iso_b/"
        c.put_object(Bucket=os.environ["S3_BUCKET"], Key=a_key, Body=b"a")
        try:
            resp = c.list_objects_v2(Bucket=os.environ["S3_BUCKET"], Prefix=b_prefix)
            if resp.get("KeyCount", 0) != 0:
                raise RuntimeError(f"prefix B unexpectedly has {resp['KeyCount']} keys")
        finally:
            c.delete_object(Bucket=os.environ["S3_BUCKET"], Key=a_key)
        return "cross_prefix_list_empty"

    def _delete(self, key: str) -> str:
        c = _client()
        c.delete_object(Bucket=os.environ["S3_BUCKET"], Key=key)
        return f"deleted {key}"


if __name__ == "__main__":
    raise SystemExit(main_for(ObjectStorageProbe))
