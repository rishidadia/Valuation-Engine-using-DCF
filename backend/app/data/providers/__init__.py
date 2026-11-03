"""Provider registry — swap providers without touching valuation code."""
from __future__ import annotations

from .base import DataProvider, MarketSnapshot, ProviderPayload
from .excel import ExcelProvider
from .public_company import PublicCompanyProvider

_REGISTRY: dict[str, type[DataProvider]] = {
    "public": PublicCompanyProvider,
    "excel": ExcelProvider,
}


def register_provider(kind: str, cls: type[DataProvider]) -> None:
    """Extension point: add e.g. an API-key provider without engine changes."""
    _REGISTRY[kind] = cls


def get_provider(kind: str) -> DataProvider:
    if kind not in _REGISTRY:
        raise KeyError(f"Unknown provider kind '{kind}'. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[kind]()


__all__ = [
    "DataProvider", "MarketSnapshot", "ProviderPayload",
    "ExcelProvider", "PublicCompanyProvider",
    "register_provider", "get_provider",
]
