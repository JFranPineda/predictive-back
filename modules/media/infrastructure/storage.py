from __future__ import annotations

from datetime import timedelta

import boto3
from django.conf import settings


class ObjectStore:
    """The only place that talks to S3/MinIO. Django never proxies bytes: it
    signs URLs and the browser talks to storage directly."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.OBJECT_STORE_ENDPOINT or None,
            aws_access_key_id=settings.OBJECT_STORE_KEY,
            aws_secret_access_key=settings.OBJECT_STORE_SECRET,
            region_name=settings.OBJECT_STORE_REGION,
        )
        self._bucket = settings.OBJECT_STORE_BUCKET

    def presign_put(self, key: str, content_type: str, expires: timedelta = timedelta(minutes=30)) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=int(expires.total_seconds()),
        )

    def presign_get(self, key: str, expires: timedelta = timedelta(minutes=15)) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=int(expires.total_seconds()),
        )

    def get(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def put(self, key: str, payload: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=payload, ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError:
            return False
        return True

    def transition(self, key: str, storage_class: str) -> None:
        self._client.copy_object(
            Bucket=self._bucket, Key=key, CopySource={"Bucket": self._bucket, "Key": key},
            StorageClass=storage_class, MetadataDirective="COPY",
        )
