"""S3-compatible adapter for immutable original document files."""

import asyncio

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from document_insight.application.ingestion.exceptions import ObjectStorageUnavailableError


class S3OriginalObjectStorage:
    """Store originals through the standard S3 API, including local MinIO."""

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        region: str,
    ) -> None:
        self._bucket_name = bucket_name
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Write an original object without blocking the event loop."""
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageUnavailableError from error

    async def delete(self, key: str) -> None:
        """Delete an object during compensation for a metadata failure."""
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket_name,
                Key=key,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageUnavailableError from error
