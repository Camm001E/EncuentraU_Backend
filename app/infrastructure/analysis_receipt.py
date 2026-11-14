import hashlib
import json

import jwt

from app.domain.object_reports import ReportValidationError


def evidence_digest(data):
    def normalize(value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [normalize(v) for v in value if not isinstance(v, str) or v.strip()]
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        return value

    raw = json.dumps(
        normalize(data),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_receipt(result, settings):
    if not settings.jwt_secret_key or not result._metadata:
        return None
    return jwt.encode(
        {
            "purpose": "image_analysis",
            "digest": evidence_digest(result.model_dump()),
            "metadata": result._metadata,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )


def verify_receipt(receipt, evidence, settings):
    try:
        if not settings.jwt_secret_key:
            raise ValueError
        payload = jwt.decode(
            receipt,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["purpose", "digest", "metadata"]},
        )
        if payload["purpose"] != "image_analysis" or payload[
            "digest"
        ] != evidence_digest(evidence):
            raise ValueError
        metadata = payload["metadata"]
        if metadata["provider"] not in {"openai", "gemini"}:
            raise ValueError
        if (
            not isinstance(metadata["model"], str)
            or not 1 <= len(metadata["model"]) <= 100
        ):
            raise ValueError
        return metadata
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise ReportValidationError from None
