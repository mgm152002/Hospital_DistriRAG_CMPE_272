"""Settings with deployment profiles (spec 4.5, 7.6). A profile fills defaults; any env var overrides them."""
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.llm import ProviderInfo

Profile = Literal["lite", "airgapped", "hybrid", "cloud"]

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "lite": {
        "run_mode": "all", "embed_provider": "hashing", "llm_provider": "none", "blob_provider": "local",
        "external_max_classification": "public", "allowed_hosts": ["postgres", "redis", "localhost"],
        "egress_enforced": True,
    },
    "airgapped": {
        "run_mode": "split", "embed_provider": "minilm", "llm_provider": "local-ollama", "blob_provider": "local",
        "external_max_classification": "public", "allowed_hosts": ["postgres", "redis", "ollama", "localhost"],
        "egress_enforced": True,
    },
    "hybrid": {
        "run_mode": "split", "embed_provider": "minilm", "llm_provider": "openrouter-free", "blob_provider": "local",
        "external_max_classification": "internal",
        "allowed_hosts": ["postgres", "redis", "localhost", "openrouter.ai"], "egress_enforced": True,
    },
    "cloud": {
        "run_mode": "split", "embed_provider": "minilm", "llm_provider": "openrouter-free", "blob_provider": "s3",
        "external_max_classification": "confidential", "allowed_hosts": [], "egress_enforced": False,
    },
}

SECRET_WORDS = ("secret", "password", "key", "token")


class ComplianceConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deployment_profile: Profile = "lite"
    # The hospital this deployment serves, shown across the UI. One deployment serves one hospital.
    hospital_name: str = "Riverside General Hospital"
    hospital_code: str = "RGH-001"
    hospital_campus: str = "Main campus"
    run_mode: Literal["all", "split"] = "all"
    database_url: str = "postgresql://distrirag:distrirag@postgres:5432/distrirag"
    redis_url: str = "redis://redis:6379/0"

    llm_provider: str = "none"
    providers_file: str = "config/providers.yaml"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "openrouter/free"
    local_proxy_base_url: str = "http://host.docker.internal:8317/v1"
    local_proxy_model: str = "gpt-6-luna"
    local_proxy_api_key: SecretStr = SecretStr("")
    chat_settings_path: str = "data/settings/chat.json"
    embed_provider: Literal["hashing", "minilm"] = "hashing"
    embedding_dim: int = 384
    model_cache_dir: str = "/models"
    blob_provider: Literal["local", "s3", "azure"] = "local"
    blob_root: str = "/data/blobs"
    s3_bucket: str = "distrirag"
    s3_endpoint_url: str = ""
    azure_connection_string: str = ""
    azure_container: str = "distrirag"

    external_max_classification: Literal["public", "internal", "confidential", "restricted"] = "public"
    allowed_hosts: list[str] = ["postgres", "redis", "localhost"]
    egress_enforced: bool = True
    synthetic_data_only: bool = True
    phi_mode: Literal["redact", "block"] = "block"  # patient data in a question is refused outright
    chat_retention_days: int = 30
    audit_retention_days: int = 365

    min_relevance: float = 0.35
    hybrid_text_weight: float = 0.3
    confidence_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)

    auth_mode: Literal["header", "local", "oidc"] = "header"
    registration_enabled: bool = True
    demo_accounts_enabled: bool = False
    demo_account_password: SecretStr = SecretStr("DemoAccess!2026")
    auth_session_hours: int = 12
    auth_cookie_secure: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    max_upload_bytes: int = 10 * 1024 * 1024
    chunk_size: int = 800
    chunk_overlap: int = 100
    embed_batch_size: int = 16
    reclaim_base_idle_ms: int = 60_000
    stuck_after_seconds: int = 600
    max_deliveries: int = 5
    worker_concurrency: int = 1
    embed_delay_ms: int = 0  # tests and drills only: slow embedding down so a worker can be killed mid-batch
    llm_max_concurrency: int = 4
    llm_answer_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    static_dir: str = "web/dist"

    @model_validator(mode="before")
    @classmethod
    def _apply_profile(cls, data: Any) -> Any:
        if isinstance(data, dict):
            profile = data.get("deployment_profile") or "lite"
            for key, value in PROFILE_DEFAULTS.get(profile, {}).items():
                data.setdefault(key, value)
            # Calibrated (docs/RESULTS.md): the hashing embedder's scores run lower than MiniLM's.
            hashing = data.get("embed_provider") == "hashing"
            data.setdefault("min_relevance", 0.15 if hashing else 0.35)
            data.setdefault("hybrid_text_weight", 0.4 if hashing else 0.3)
        return data

    def hospital(self) -> dict[str, str]:
        """The hospital this deployment serves. Public: the sign-in screens name it."""
        return {"name": self.hospital_name, "code": self.hospital_code, "campus": self.hospital_campus}

    def public_view(self) -> dict[str, Any]:
        view: dict[str, Any] = {}
        for key, value in self.model_dump().items():
            if any(word in key for word in SECRET_WORDS):
                view[key] = "***" if value else ""
            elif key.endswith("_url") and isinstance(value, str) and "@" in value:
                scheme, _, rest = value.partition("://")
                view[key] = f"{scheme}://***@{rest.split('@', 1)[1]}"
            else:
                view[key] = value
        return view


def validate_compliance(s: Settings, providers: dict[str, ProviderInfo]) -> None:
    """Refuse to start with a configuration that would break the compliance rules (spec CP-4, CP-8, DP-5)."""
    if s.demo_accounts_enabled and not s.synthetic_data_only:
        raise ComplianceConfigError("Demo accounts require SYNTHETIC_DATA_ONLY=true")
    if s.llm_provider not in ("none", "fake") and s.llm_provider not in providers:
        raise ComplianceConfigError(f"Unknown LLM provider {s.llm_provider!r}; add it to {s.providers_file}")
    info = providers.get(s.llm_provider)
    if info and info.external:
        if s.deployment_profile == "airgapped":
            raise ComplianceConfigError("The air-gapped profile cannot use an external LLM provider")
        if not s.synthetic_data_only and info.retains_data:
            raise ComplianceConfigError(
                f"{info.name} retains prompts; it is allowed only with synthetic data (SYNTHETIC_DATA_ONLY=true)")
        if not s.synthetic_data_only and not info.baa_signed:
            raise ComplianceConfigError(f"{info.name} has no signed BAA; real data needs one")
    if s.deployment_profile == "cloud" and "sslmode=require" not in s.database_url:
        raise ComplianceConfigError("The cloud profile needs DATABASE_URL with sslmode=require")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
