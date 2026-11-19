"""Read-only collection of authorized company API extracts."""

from .collect import CollectionError, collect_json, validate_config

__all__ = ["CollectionError", "collect_json", "validate_config"]
