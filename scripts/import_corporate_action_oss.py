from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
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
    MIN_CONFIDENCE,
    archive_candidates,
    deduplicate_events,
    imported_object_exists,
    quarantine_import_row,
    record_run,
    record_imported_object,
    save_events,
    source_quality,
)


SCHEMA_VERSION = "corporate-action-candidate/v1"
DIRECT_EVENT_SCHEMA_VERSION = "corporate-action-event/v2"
DEFAULT_PREFIX = "corporate-actions/v1/incoming/"
DEFAULT_MAX_OBJECT_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_OBJECT_ROWS = 1000
DEFAULT_MAX_V1_CANDIDATES = 200
DEFAULT_LOOKBACK_DAYS = 30
READ_CHUNK_BYTES = 64 * 1024
OSS_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


@dataclass(frozen=True)
class OssConfig:
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    prefix: str
    max_object_bytes: int
    max_object_rows: int
    max_v1_candidates: int
    lookback_days: int


@dataclass(frozen=True)
class OssObjectRef:
    key: str
    etag: str
    size: int


@dataclass(frozen=True)
class RejectedRow:
    line_number: int
    raw_payload: str
    error_code: str
    error_summary: str
    market: str = ""
    schema_version: str = ""
    source_agent: str = ""


class ImportValidationError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


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
        max_object_rows=int(os.getenv("CORPORATE_ACTION_OSS_MAX_OBJECT_ROWS", str(DEFAULT_MAX_OBJECT_ROWS))),
        max_v1_candidates=int(os.getenv("CORPORATE_ACTION_OSS_MAX_V1_CANDIDATES", str(DEFAULT_MAX_V1_CANDIDATES))),
        lookback_days=int(os.getenv("CORPORATE_ACTION_OSS_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS))),
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
    if config.max_object_rows < 1:
        raise ValueError("CORPORATE_ACTION_OSS_MAX_OBJECT_ROWS must be positive")
    if config.max_v1_candidates < 1:
        raise ValueError("CORPORATE_ACTION_OSS_MAX_V1_CANDIDATES must be positive")
    if not 1 <= config.lookback_days <= 365:
        raise ValueError("CORPORATE_ACTION_OSS_LOOKBACK_DAYS must be between 1 and 365")
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


def _response_attribute(response: Any, name: str) -> str:
    value = getattr(response, name, "")
    if value:
        return str(value).strip().strip('"')
    headers = getattr(response, "headers", {}) or {}
    return str(headers.get(name) or headers.get(name.title()) or "").strip().strip('"')


def read_object_payload(bucket: Any, object_key: str, max_object_bytes: int, expected_etag: str = "") -> bytes:
    """Read an OSS object incrementally and reject a changed or oversized body."""
    response = oss_read_with_retry(lambda: bucket.get_object(object_key))
    response_etag = _response_attribute(response, "etag")
    if expected_etag and response_etag and response_etag != expected_etag.strip().strip('"'):
        raise ValueError(f"object changed while importing: expected ETag {expected_etag}, got {response_etag}")
    content_length = _response_attribute(response, "content_length")
    if content_length:
        try:
            if int(content_length) > max_object_bytes:
                raise ValueError(f"object size {content_length} exceeds limit {max_object_bytes}")
        except ValueError as exc:
            if "exceeds limit" in str(exc):
                raise
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = response.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_object_bytes:
                raise ValueError(f"object body exceeds limit {max_object_bytes}")
            chunks.append(chunk)
    except TypeError:
        # Maintains compatibility with lightweight test doubles and older OSS response wrappers.
        payload = response.read()
        if len(payload) > max_object_bytes:
            raise ValueError(f"object body exceeds limit {max_object_bytes}")
        return payload
    return b"".join(chunks)


def _validate_published_window(
    published_at: str, object_key: str, line_number: int, as_of_date: date, lookback_days: int,
) -> None:
    published = date.fromisoformat(published_at)
    start = as_of_date - timedelta(days=lookback_days)
    end = as_of_date + timedelta(days=1)
    if not start <= published <= end:
        raise ImportValidationError(
            "out_of_window",
            f"{object_key}:{line_number}: published_at must be between {start.isoformat()} and {end.isoformat()}",
        )


def validate_candidate(
    value: object, object_key: str, line_number: int, as_of_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[dict[str, Any], str]:
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
    _validate_iso_date(published_at, "published_at", object_key, line_number)
    _validate_published_window(published_at, object_key, line_number, as_of_date or date.today(), lookback_days)
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


def _required_text(value: dict[str, Any], field: str, object_key: str, line_number: int, limit: int) -> str:
    text = str(value.get(field) or "").strip()
    if not text:
        raise ValueError(f"{object_key}:{line_number}: {field} is required")
    if len(text) > limit:
        raise ValueError(f"{object_key}:{line_number}: {field} exceeds {limit} characters")
    return text


def _optional_text(value: dict[str, Any], field: str, limit: int) -> str:
    return str(value.get(field) or "").strip()[:limit]


def _validate_iso_date(value: str, field: str, object_key: str, line_number: int) -> None:
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"{object_key}:{line_number}: {field} must use YYYY-MM-DD") from exc


def validate_direct_event(
    value: object, object_key: str, line_number: int, as_of_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[dict[str, Any], str]:
    """Validate a v2 event without invoking the LLM or making network requests."""
    if not isinstance(value, dict):
        raise ValueError(f"{object_key}:{line_number}: each JSONL row must be an object")
    if value.get("schema_version") != DIRECT_EVENT_SCHEMA_VERSION:
        raise ValueError(f"{object_key}:{line_number}: schema_version must be {DIRECT_EVENT_SCHEMA_VERSION}")
    agent_record_id = _required_text(value, "agent_record_id", object_key, line_number, 200)
    source_agent = _required_text(value, "source_agent", object_key, line_number, 200)
    market = _required_text(value, "market", object_key, line_number, 8).lower()
    if market not in MARKETS:
        raise ValueError(f"{object_key}:{line_number}: market must be one of {', '.join(MARKETS)}")
    event_type = _required_text(value, "event_type", object_key, line_number, 20).lower()
    if event_type not in EVENT_TYPES:
        raise ValueError(f"{object_key}:{line_number}: event_type must be one of {', '.join(EVENT_TYPES)}")
    event_stage = _required_text(value, "event_stage", object_key, line_number, 30).lower()
    if event_stage not in EVENT_STAGES:
        raise ValueError(f"{object_key}:{line_number}: invalid event_stage")
    company_name = _required_text(value, "company_name", object_key, line_number, 500)
    headline = _required_text(value, "headline", object_key, line_number, 500)
    headline_zh = _required_text(value, "headline_zh", object_key, line_number, 500)
    summary_zh = _required_text(value, "summary_zh", object_key, line_number, 1000)
    evidence_text = _required_text(value, "evidence_text", object_key, line_number, 1000)
    source_url = _required_text(value, "source_url", object_key, line_number, 2000)
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError(f"{object_key}:{line_number}: source_url must be an absolute HTTP(S) URL")
    published_at = _required_text(value, "published_at", object_key, line_number, 10)
    _validate_iso_date(published_at, "published_at", object_key, line_number)
    _validate_published_window(published_at, object_key, line_number, as_of_date or date.today(), lookback_days)
    quality = _required_text(value, "source_quality", object_key, line_number, 20).lower()
    if quality not in {"primary", "mainstream", "other"}:
        raise ValueError(f"{object_key}:{line_number}: invalid source_quality")
    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{object_key}:{line_number}: confidence must be a number") from exc
    if not MIN_CONFIDENCE <= confidence <= 1:
        raise ValueError(f"{object_key}:{line_number}: confidence must be between {MIN_CONFIDENCE} and 1")
    event_date = _optional_text(value, "event_date", 10)
    if event_date:
        _validate_iso_date(event_date, "event_date", object_key, line_number)
    event = {
        "agent_record_id": agent_record_id,
        "market": market,
        "ticker": _optional_text(value, "ticker", 40),
        "company_name": company_name,
        "exchange": _optional_text(value, "exchange", 100),
        "event_type": event_type,
        "event_stage": event_stage,
        "actor_name": _optional_text(value, "actor_name", 500),
        "actor_type": _optional_text(value, "actor_type", 200),
        "headline": headline,
        "headline_zh": headline_zh,
        "summary_zh": summary_zh,
        "quantity_text": _optional_text(value, "quantity_text", 500),
        "amount_text": _optional_text(value, "amount_text", 500),
        "ownership_change_text": _optional_text(value, "ownership_change_text", 500),
        "published_at": published_at,
        "event_date": event_date,
        "source_url": source_url,
        "source_domain": _optional_text(value, "source_domain", 255) or parsed_url.netloc.lower(),
        "source_quality": quality,
        "confidence": confidence,
        "source_schema": DIRECT_EVENT_SCHEMA_VERSION,
        "source_agent": source_agent,
        "evidence_text": evidence_text,
    }
    return event, source_agent


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


def parse_import_jsonl(
    payload: bytes, object_key: str, max_rows: int = DEFAULT_MAX_OBJECT_ROWS, max_v1_candidates: int = DEFAULT_MAX_V1_CANDIDATES,
    as_of_date: date | None = None, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[RejectedRow], str]:
    """Parse both schemas and retain rejected rows for the import quarantine."""
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{object_key}: file must be UTF-8 JSONL") from exc
    candidates: list[dict[str, Any]] = []
    direct_events: list[dict[str, Any]] = []
    rejected: list[RejectedRow] = []
    source_agent = ""
    direct_ids: set[str] = set()
    total_rows = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        total_rows += 1
        if total_rows > max_rows:
            raise ValueError(f"{object_key}: row count exceeds limit {max_rows}")
        raw_payload = line.strip()
        market = ""
        schema_version = ""
        row_agent = ""
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                market = str(value.get("market") or "").strip().lower()
                schema_version = str(value.get("schema_version") or "").strip()
                row_agent = str(value.get("source_agent") or "").strip()[:200]
                if row_agent and not source_agent:
                    source_agent = row_agent
            if schema_version == SCHEMA_VERSION:
                candidate, row_agent = validate_candidate(value, object_key, line_number, as_of_date, lookback_days)
                candidates.append(candidate)
            elif schema_version == DIRECT_EVENT_SCHEMA_VERSION:
                event, row_agent = validate_direct_event(value, object_key, line_number, as_of_date, lookback_days)
                if event["agent_record_id"] in direct_ids:
                    raise ValueError(f"{object_key}:{line_number}: duplicate agent_record_id in object")
                direct_ids.add(event["agent_record_id"])
                direct_events.append(event)
            else:
                raise ValueError(f"{object_key}:{line_number}: unsupported schema_version")
        except (json.JSONDecodeError, ValueError) as exc:
            message = str(exc)
            error_code = "invalid_json" if isinstance(exc, json.JSONDecodeError) else getattr(exc, "error_code", "validation_error")
            rejected.append(RejectedRow(line_number, raw_payload, error_code, message, market, schema_version, row_agent))
    if len(candidates) > max_v1_candidates:
        raise ValueError(f"{object_key}: v1 candidate count exceeds limit {max_v1_candidates}")
    return candidates, direct_events, rejected, source_agent


def import_object(
    bucket: Any, bucket_name: str, object_key: str, etag: str, size: int, max_object_bytes: int,
    dry_run: bool = False, db_path: Path = CORPORATE_ACTION_NEWS_DB, max_rows: int = DEFAULT_MAX_OBJECT_ROWS,
    max_v1_candidates: int = DEFAULT_MAX_V1_CANDIDATES, retry_partial: bool = False,
    as_of_date: date | None = None, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    if size > max_object_bytes:
        message = f"object size {size} exceeds limit {max_object_bytes}"
        if not dry_run:
            if imported_object_exists(bucket_name, object_key, etag, db_path, include_partial=False, include_rejected_oversize=True):
                return {"object_key": object_key, "etag": etag, "status": "skipped", "reason": "oversize_already_rejected"}
            record_imported_object(bucket_name, object_key, etag, "rejected_oversize", 0, 0, 0, errors=[message], db_path=db_path)
        return {"object_key": object_key, "etag": etag, "status": "rejected", "error": message}
    if not dry_run and imported_object_exists(bucket_name, object_key, etag, db_path, include_partial=not retry_partial):
        return {"object_key": object_key, "etag": etag, "status": "skipped", "reason": "already_imported"}
    try:
        payload = read_object_payload(bucket, object_key, max_object_bytes, etag)
        candidates, direct_events, rejected_rows, source_agent = parse_import_jsonl(
            payload, object_key, max_rows, max_v1_candidates, as_of_date, lookback_days,
        )
        v1_events = []
        diagnostics: list[str] = []
        for market in MARKETS:
            market_candidates = [candidate for candidate in candidates if candidate["market"] == market]
            if market_candidates:
                market_events = archive_candidates(market_candidates, market, db_path, write=not dry_run, diagnostics=diagnostics)
                if not market_events:
                    diagnostics.append(f"v1_no_valid_events: market={market}")
                v1_events.extend(market_events)
        v2_events = deduplicate_events(direct_events)
        if not dry_run and v2_events:
            save_events(v2_events, db_path)
        events = v1_events + v2_events
        errors = [row.error_summary for row in rejected_rows] + diagnostics
        if not dry_run:
            for row in rejected_rows:
                quarantine_import_row(
                    bucket_name, object_key, etag, row.line_number, row.raw_payload, row.error_code, row.error_summary,
                    row.market, row.schema_version, row.source_agent, db_path,
                )
        total_rows = len([line for line in payload.decode("utf-8-sig").splitlines() if line.strip()])
        rejected = len(rejected_rows)
        accepted = total_rows - rejected
        stored_event_count = len(events)
        deduplicated_v2_rows = len(direct_events) - len(v2_events)
        status = "partial" if errors else "ok"
        if not dry_run:
            record_imported_object(
                bucket_name, object_key, etag, status, total_rows, accepted, rejected,
                stored_event_count=stored_event_count, deduplicated_v2_rows=deduplicated_v2_rows,
                source_agent=source_agent, errors=errors, db_path=db_path,
            )
            # An imported batch with valid events is a successful data refresh
            # even though it did not originate from the web search collector.
            # Recording it here keeps the status endpoint and default 30-day
            # query window in sync with data delivered by other agents.
            refresh_as_of = as_of_date or date.today()
            refresh_start = refresh_as_of - timedelta(days=lookback_days)
            for market in sorted({str(item.get("market", "")) for item in events}):
                if market not in MARKETS:
                    continue
                market_events = [item for item in events if item.get("market") == market]
                market_candidates = [item for item in candidates if item.get("market") == market]
                record_run(
                    market,
                    refresh_as_of,
                    refresh_start,
                    status,
                    task_count=0,
                    candidate_count=len(market_candidates) + len([item for item in direct_events if item.get("market") == market]),
                    stored_count=len(market_events),
                    errors=errors,
                    db_path=db_path,
                )
        return {
            "object_key": object_key,
            "etag": etag,
            "status": status,
            "total_rows": total_rows,
            "accepted_rows": accepted,
            "rejected_rows": rejected,
            "quarantined_rows": len(rejected_rows),
            "stored_event_count": stored_event_count,
            "deduplicated_v2_rows": deduplicated_v2_rows,
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
    parser.add_argument("--retry-partial", action="store_true", help="Reprocess objects previously recorded as partial; safe because event and quarantine writes are idempotent.")
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
                config.max_object_bytes, args.dry_run, max_rows=config.max_object_rows,
                max_v1_candidates=config.max_v1_candidates, retry_partial=args.retry_partial,
                lookback_days=config.lookback_days,
            )
        )
    summary = {
        "bucket": config.bucket,
        "prefix": prefix,
        "dry_run": args.dry_run,
        "retry_partial": args.retry_partial,
        "objects_seen": len(results),
        "objects_ok": sum(item.get("status") == "ok" for item in results),
        "objects_partial": sum(item.get("status") == "partial" for item in results),
        "objects_rejected": sum(item.get("status") == "rejected" for item in results),
        "objects_skipped": sum(item.get("status") == "skipped" for item in results),
        "objects_failed": sum(item.get("status") == "failed" for item in results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    if summary["objects_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
