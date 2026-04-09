"""Structured logging setup with a PHI-redaction processor.

Call configure_logging() once at process start (e.g. from main.py). All modules
should obtain a logger via ``structlog.get_logger(__name__)`` so log lines
carry their origin and any bound context.

PHI redaction
-------------
The structlog processor pipeline includes ``redact_phi``, which walks every
value on every log event and replaces fields whose key is on the PHI deny-list
with ``***REDACTED***``. The deny-list is built from two sources:

    1. Field metadata on the member_record Pydantic schemas — any field
       declared with ``Field(json_schema_extra={"phi": True})`` is collected
       at import time. Adding a new PHI field to the schemas automatically
       redacts it in logs without touching this module.
    2. A hard-coded fallback set of common PHI key names so generic dicts
       (raw event attributes, third-party payloads, ad-hoc bound context)
       are also covered.

The redactor walks nested dicts and lists. It never raises — anything it
cannot reason about is passed through untouched so a malformed event can
never take the logger down.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Iterable

import structlog

REDACTED = "***REDACTED***"

# Hard-coded PHI keys we always redact in logs, regardless of which module
# emitted the log line. Lowercased for case-insensitive matching.
_BASELINE_PHI_KEYS: frozenset[str] = frozenset(
    {
        "ssn",
        "social_security_number",
        "dob",
        "date_of_birth",
        "first_name",
        "last_name",
        "full_name",
        "phone",
        "phone_number",
        "email",
        "address",
        "street",
        "mrn",
        "medical_record_number",
        "npi",  # bare NPI; npi_hash is fine
    },
)


def _collect_schema_phi_keys() -> set[str]:
    """Walk member_record.schemas and collect every field tagged phi=True."""
    keys: set[str] = set()
    try:
        from pydantic import BaseModel

        from .member_record import schemas as member_schemas
    except Exception:  # pragma: no cover - defensive at import time
        return keys

    for obj in vars(member_schemas).values():
        if not isinstance(obj, type) or not issubclass(obj, BaseModel) or obj is BaseModel:
            continue
        for name, field in obj.model_fields.items():
            extra = field.json_schema_extra
            if isinstance(extra, dict) and extra.get("phi"):
                keys.add(name.lower())
    return keys


def _build_phi_keys() -> frozenset[str]:
    return frozenset(_BASELINE_PHI_KEYS | _collect_schema_phi_keys())


PHI_KEYS: frozenset[str] = _build_phi_keys()


def _redact_value(value: Any, phi_keys: Iterable[str]) -> Any:
    """Walk dicts / lists / tuples, redact PHI-keyed leaves."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if isinstance(k, str) and k.lower() in phi_keys else _redact_value(v, phi_keys))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(v, phi_keys) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v, phi_keys) for v in value)
    return value


def redact_phi(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: redact PHI keys anywhere in the event dict.

    Top-level keys whose name matches PHI_KEYS get their value replaced
    outright. Nested dicts and lists are walked recursively. The processor
    is intentionally exception-tolerant — anything it cannot reason about
    is passed through untouched so a malformed event can never crash the
    logger.
    """
    try:
        return {
            k: (REDACTED if isinstance(k, str) and k.lower() in PHI_KEYS else _redact_value(v, PHI_KEYS))
            for k, v in event_dict.items()
        }
    except Exception:  # pragma: no cover - never let logging fail
        return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_phi,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
