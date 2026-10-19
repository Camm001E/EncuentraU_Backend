"""Persisted scoring provenance, shared across layers.

Legacy identifiers are immutable: migrations and historical decisions use them.
Only CURRENT_SCORING_VERSION changes for a future scoring implementation.
"""

LEGACY_SCORING_VERSION = "legacy-v1"
CURRENT_SCORING_VERSION = "semantic-v2"
SCORING_VERSION_MAX_LENGTH = 64
