"""Application configuration.

All secrets come from environment variables. No keys are ever hardcoded.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore", case_sensitive=False)

    app_name: str = "DCF labs"
    app_tagline: str = "Computational Valuation Engine"
    environment: str = "development"
    debug: bool = False

    # Database: PostgreSQL in production, SQLite for local development.
    # e.g. postgresql+psycopg2://user:pass@localhost:5432/dcf_labs
    database_url: str = f"sqlite:///{BASE_DIR / 'dcf_labs.db'}"

    # CORS — explicit allow list, never "*" when keys are configured.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- External data providers (all keyless sources by default) ---
    sec_user_agent: str = "DCF labs research agent (contact@example.com)"
    sec_company_tickers_url: str = "https://www.sec.gov/files/company_tickers.json"
    sec_company_facts_url: str = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    yahoo_chart_url: str = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    fred_risk_free_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"

    http_timeout_seconds: float = 20.0
    provider_cache_ttl_seconds: int = 3600

    # --- Uploads ---
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    allowed_upload_extensions: str = ".xlsx"

    # --- LLM (optional). Pipeline is fully deterministic without it. ---
    llm_provider: str = "auto"  # auto | openai | groq | google | none
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    google_api_key: str | None = None
    llm_model: str | None = None

    # Valuation defaults (always surfaced as MODEL ASSUMPTION in the UI)
    default_forecast_years: int = 5
    default_market_risk_premium: float = 0.050
    default_tax_rate: float = 0.21
    default_risk_free_rate: float = 0.040

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
