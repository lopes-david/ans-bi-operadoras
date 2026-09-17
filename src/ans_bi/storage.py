"""Acesso ao data lake: S3 na nuvem ou diretório local no desenvolvimento.

Chaves são sempre relativas à raiz do lake (ex.: "silver/igr/data.parquet").
"""

from __future__ import annotations

import json
import shutil
from functools import cached_property
from pathlib import Path
from typing import Any

from .config import Settings


class Lake:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.lake_uri
        if settings.is_s3:
            self.bucket = self.root.removeprefix("s3://").split("/", 1)[0]
            rest = self.root.removeprefix(f"s3://{self.bucket}").strip("/")
            self.prefix = f"{rest}/" if rest else ""
        else:
            self.local_root = Path(self.root)

    @cached_property
    def _s3(self):
        import boto3  # disponível no runtime da Lambda; localmente vem do grupo dev

        return boto3.client("s3")

    def uri(self, key: str) -> str:
        """Caminho que o DuckDB entende (s3://... ou caminho local)."""
        if self.settings.is_s3:
            return f"s3://{self.bucket}/{self.prefix}{key}"
        return str(self.local_root / key)

    def _k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def read_json(self, key: str) -> Any | None:
        if self.settings.is_s3:
            try:
                body = self._s3.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()
            except self._s3.exceptions.NoSuchKey:
                return None
            return json.loads(body)
        path = self.local_root / key
        return json.loads(path.read_text()) if path.exists() else None

    def write_json(self, key: str, data: Any, cache_control: str | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=1, default=str).encode()
        if self.settings.is_s3:
            extra = {"CacheControl": cache_control} if cache_control else {}
            self._s3.put_object(
                Bucket=self.bucket, Key=self._k(key), Body=body, ContentType="application/json", **extra
            )
            return
        path = self.local_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def upload_file(
        self, src: Path, key: str, content_type: str = "application/octet-stream", cache_control: str | None = None
    ) -> None:
        if self.settings.is_s3:
            extra: dict[str, str] = {"ContentType": content_type}
            if cache_control:
                extra["CacheControl"] = cache_control
            self._s3.upload_file(str(src), self.bucket, self._k(key), ExtraArgs=extra)
            return
        dst = self.local_root / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def list_keys(self, prefix: str) -> list[str]:
        if self.settings.is_s3:
            keys: list[str] = []
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self._k(prefix)):
                keys += [o["Key"].removeprefix(self.prefix) for o in page.get("Contents", [])]
            return keys
        # prefixo pode terminar no meio de um nome (ex.: "state/done/x/2026-07/SP@")
        base = self.local_root / prefix
        search = base if prefix.endswith("/") else base.parent
        if not search.exists():
            return []
        keys = (p.relative_to(self.local_root).as_posix() for p in search.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix))

    def exists(self, prefix: str) -> bool:
        return bool(self.list_keys(prefix))

    def delete_keys(self, keys: list[str]) -> None:
        if not keys:
            return
        if self.settings.is_s3:
            for i in range(0, len(keys), 1000):
                chunk = [{"Key": self._k(k)} for k in keys[i : i + 1000]]
                self._s3.delete_objects(Bucket=self.bucket, Delete={"Objects": chunk, "Quiet": True})
            return
        for k in keys:
            (self.local_root / k).unlink(missing_ok=True)
