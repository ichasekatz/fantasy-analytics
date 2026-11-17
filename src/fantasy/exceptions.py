"""Custom exceptions for the fantasy analytics package."""

from __future__ import annotations


class DataIngestionError(ValueError):
    """Raised when the JSON export cannot be parsed or is structurally invalid."""


class MissingSeasonError(KeyError):
    """Raised when a requested season has no data in the database."""


class ScoringError(RuntimeError):
    """Raised when fantasy points cannot be computed due to missing or inconsistent data."""
