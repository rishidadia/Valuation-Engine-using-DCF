"""Structured application errors.

Every failure surfaces an explicit, human-readable reason. The application
never silently continues with fabricated numbers.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for all DCF-labs errors."""

    code: str = "app_error"
    http_status: int = 400

    def __init__(self, detail: str, *, hint: str | None = None):
        self.detail = detail
        self.hint = hint
        super().__init__(detail)

    def to_dict(self) -> dict:
        d = {"error": self.code, "detail": self.detail}
        if self.hint:
            d["hint"] = self.hint
        return d


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422


class ProviderError(AppError):
    """External data provider failed (network, rate limit, bad symbol...)."""

    code = "provider_error"
    http_status = 502


class TickerNotFoundError(ProviderError):
    code = "ticker_not_found"
    http_status = 404


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    http_status = 503


class ExcelValidationError(AppError):
    code = "excel_invalid"
    http_status = 422


class MissingDataError(AppError):
    """A required input is missing and cannot be derived without fabricating."""

    code = "missing_data"
    http_status = 422


class ValuationError(AppError):
    code = "valuation_error"
    http_status = 422


class TerminalValueError(ValuationError):
    """WACC <= terminal growth: perpetuity terminal value is undefined."""

    code = "terminal_value_invalid"


class AuditBlockedError(ValuationError):
    """Audit agent returned FAIL; final valuation cannot be marked complete."""

    code = "audit_blocked"
    http_status = 409
