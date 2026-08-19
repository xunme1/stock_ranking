from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import oss2
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.core.config import CORPORATE_ACTION_NEWS_DB  # noqa: E402
from app.services.corporate_action_news_service import (  # noqa: E402
    EVENT_STAGES,
    EVENT_TYPES,
    MARKETS,
    archive_candidates,
    imported_object_exists,
    record_imported_object,
    source_quality,
)


SCHEMA_VERSION = "corporate-action-candidate/v1"
DEFAULT_PREFIX = "corporate-actions/v1/incoming/"
DEFAULT_MAX_OBJECT_BYTES = 5 * 1024 * 1024
OSS_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


@dataclass(frozen=True)
class OssConfig:
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    prefix: str
    max_object_bytes: int


@dataclass(frozen=True)
class OssObjectRef:
    key: str
    etag: str
    size: int


def _env(primary: str, legacy: str) -> str:
    return (os.getenv(primary, "").strip() or os.getenv(legacy, "").strip())


def load_oss_config() -> OssConfig:
    load_dotenv(ROOT_DIR / ".env")
    config = OssConfig(
        endpoint=_env("CORPORATE_ACTION_OSS_ENDPOINT", "END_POINT"),
        bucket=_env("CORPORATE_ACTION_OSS_BUCKET", "BUCKET"),
        access_key_id=_env("CORPORATE_ACTION_OSS_ACCESS_KEY_ID", "ACCESS_KEY_ID"),
        access_key_secret=_env("CORPORATE_ACTION_OSS_ACCESS_KEY_SECRET", "ACCESS_KEY_SECRET"),
        prefix=os.getenv("CORPORATE_ACTION_OSS_PREFIX", DEFAULT_PREFIX).strip().strip("/") + "/",
        max_object_bytes=int(os.getenv("CORPORATE_ACTION_OSS_MAX_OBJECT_BYTES", str(DEFAULT_MAX_OBJECT_BYTES))),
    )
    missing = [
        name
        for name, value in {
            "CORPORATE_ACTION_OSS_ENDPOINT (or END_POINT)": config.endpoint,
            "CORPORATE_ACTION_OSS_BUCKET (or BUCKET)": config.bucket,
            "CORPORATE_ACTION_OSS_ACCESS_KEY_ID (or ACCESS_KEY_ID)": config.access_key_id,
            "CORPORATE_ACTION_OSS_ACCESS_KEY_SECRET (or ACCESS_KEY_SECRET)": config.access_key_secret,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError("Missing OSS configuration: " + ", ".join(missing))
    if config.max_object_bytes < 1:
        raise ValueError("CORPORATE_ACTION_OSS_MAX_OBJECT_BYTES must be positive")
    return config


def build_bucket(config: OssConfig) -> oss2.Bucket:
    return oss2.Bucket(
        oss2.Auth(config.access_key_id, config.access_key_secret),
        config.endpoint,
        config.bucket,
        connect_timeout=20,
    )


def oss_read_with_retry(operation: Any, attempts: int = 3) -> Any:
    """Retry only transient OSS read failures; write operations are never retried here."""
    for attempt in range(attempts):
        try:
            return operation()
        except oss2.exceptions.OssError as exc:
            if exc.status not in OSS_RETRYABLE_STATUS_CODES or attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def validate_candidate(value: object, object_key: str, line_number: int) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        raise ValueError(f"{object_key}:{line_number}: each JSONL row must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{object_key}:{line_number}: schema_version must be {SCHEMA_VERSION}")
    market = str(value.get("market") or "").strip().lower()
    if market not in MARKETS:
        raise ValueError(f"{object_key}:{line_number}: market must be one of {', '.join(MARKETS)}")
    event_type = str(value.get("event_type") or "").strip().lower()
    if event_type not in EVENT_TYPES:
        raise ValueError(f"{object_key}:{line_number}: event_type must be one of {', '.join(EVENT_TYPES)}")
    headline = str(value.get("headline") or "").strip()
    if not headline:
        raise ValueError(f"{object_key}:{line_number}: headline is required")
    source_url = str(value.get("source_url") or "").strip()
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError(f"{object_key}:{line_number}: source_url must be an absolute HTTP(S) URL")
    published_at = str(value.get("published_at") or "").strip()
    try:
        date.fromisoformat(published_at)
    except ValueError as exc:
        raise ValueError(f"{object_key}:{line_number}: published_at must use YYYY-MM-DD") from exc
    event_stage = str(value.get("event_stage") or "announced").strip().lower()
    if event_stage not in EVENT_STAGES:
        raise ValueError(f"{object_key}:{line_number}: invalid event_stage")
    quality = str(value.get("source_quality") or source_quality(source_url)).strip().lower()
    if quality not in {"primary", "mainstream", "other"}:
        quality = "other"
    candidate = {
        "market": market,
        "event_type": event_type,
        "event_stage": event_stage,
        "headline": headline[:500],
        "snippet": str(value.get("snippet") or "").strip()[:2000],
        "published_at": published_at,
        "source_url": source_url,
        "source_domain": str(value.get("source_domain") or parsed_url.netloc.lower()).strip().lower(),
        "source_quality": quality,
    }
    return candidate, str(value.get("source_agent") or "").strip()[:200]


def parse_jsonl(payload: bytes, object_key: str) -> tuple[list[dict[str, Any]], list[str], str]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{object_key}: file must be UTF-8 JSONL") from exc
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    source_agent = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            candidate, row_agent = validate_candidate(json.loads(line), object_key, line_number)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        candidates.append(candidate)
        if row_agent and not source_agent:
            source_agent = row_agent
    return candidates, errors, source_agent


def import_object(bucket: Any, bucket_name: str, object_key: str, etag: str, size: int, max_object_bytes: int, dry_run: bool = False, db_path: Path = CORPORATE_ACTION_NEWS_DB) -> dict[str, Any]:
    if size > max_object_bytes:
        message = f"object size {size} exceeds limit {max_object_bytes}"
        if not dry_run:
            record_imported_object(bucket_name, object_key, etag, "failed", 0, 0, 0, errors=[message], db_path=db_path)
        return {"object_key": object_key, "etag": etag, "status": "failed", "error": message}
    if not dry_run and imported_object_exists(bucket_name, object_key, etag, db_path):
        return {"object_key": object_key, "etag": etag, "status": "skipped", "reason": "already_imported"}
    try:
        payload = oss_read_with_retry(lambda: bucket.get_object(object_key).read())
        candidates, errors, source_agent = parse_jsonl(payload, object_key)
        events = [
            event
            for market in MARKETS
            for event in archive_candidates([candidate for candidate in candidates if candidate["market"] == market], market, db_path, write=not dry_run)
        ]
        total_rows = len([line for line in payload.decode("utf-8-sig").splitlines() if line.strip()])
        accepted = len(events)
        rejected = total_rows - accepted
        if accepted == 0 and total_rows:
            errors.append("no rows passed structural validation and event extraction")
        status = "ok" if rejected == 0 else "partial"
        if not dry_run:
            record_imported_object(
                bucket_name, object_key, etag, status, total_rows, accepted, rejected,
                source_agent=source_agent, errors=errors, db_path=db_path,
            )
        return {
            "object_key": object_key,
            "etag": etag,
            "status": status,
            "total_rows": total_rows,
            "accepted_rows": accepted,
            "rejected_rows": rejected,
            "errors": errors[:10],
        }
    except Exception as exc:
        if not dry_run:
            record_imported_object(bucket_name, object_key, etag, "failed", 0, 0, 0, errors=[str(exc)], db_path=db_path)
        return {"object_key": object_key, "etag": etag, "status": "failed", "error": str(exc)}


def iter_objects(bucket: oss2.Bucket, prefix: str, max_objects: int) -> Iterable[OssObjectRef]:
    count = 0
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        if obj.key.endswith("/"):
            continue
        yield OssObjectRef(obj.key, str(obj.etag), int(obj.size))
        count += 1
        if count >= max_objects:
            return


def explicit_objects(bucket: oss2.Bucket, object_keys: Iterable[str]) -> list[OssObjectRef]:
    """Resolve named objects without requiring ListBucket permission."""
    objects: list[OssObjectRef] = []
    for object_key in dict.fromkeys(key.strip().lstrip("/") for key in object_keys if key.strip()):
        metadata = oss_read_with_retry(lambda: bucket.head_object(object_key))
        objects.append(OssObjectRef(object_key, str(metadata.etag), int(metadata.content_length)))
    return objects


def main() -> None:
    parser = argparse.ArgumentParser(description="Import standardized corporate-action candidate JSONL batches from OSS.")
    parser.add_argument("--prefix", default=None, help="Override incoming OSS prefix.")
    parser.add_argument(
        "--object-key", action="append", default=[], metavar="KEY",
        help="Import this exact OSS object key; repeatable and does not require ListBucket permission.",
    )
    parser.add_argument("--max-objects", type=int, default=100, metavar="N", help="Maximum OSS objects per run. Defaults to 100.")
    parser.add_argument("--dry-run", action="store_true", help="Download, validate, and structure data without SQLite writes or import audit records.")
    args = parser.parse_args()
    if args.max_objects < 1:
        raise SystemExit("--max-objects must be positive")
    config = load_oss_config()
    prefix = (args.prefix or config.prefix).strip().strip("/") + "/"
    bucket = build_bucket(config)
    try:
        objects = explicit_objects(bucket, args.object_key) if args.object_key else list(iter_objects(bucket, prefix, args.max_objects))
    except oss2.exceptions.OssError as exc:
        if exc.status == 403 and not args.object_key:
            raise SystemExit("OSS ListBucket permission is required for prefix scanning. Grant oss:ListObjects on the incoming prefix or use --object-key KEY.") from exc
        raise
    results = []
    for obj in objects:
        results.append(
            import_object(
                bucket, config.bucket, obj.key, obj.etag, obj.size,
                config.max_object_bytes, args.dry_run,
            )
        )
    summary = {
        "bucket": config.bucket,
        "prefix": prefix,
        "dry_run": args.dry_run,
        "objects_seen": len(results),
        "objects_ok": sum(item.get("status") == "ok" for item in results),
        "objects_partial": sum(item.get("status") == "partial" for item in results),
        "objects_skipped": sum(item.get("status") == "skipped" for item in results),
        "objects_failed": sum(item.get("status") == "failed" for item in results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    if summary["objects_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
