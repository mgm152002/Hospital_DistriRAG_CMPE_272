"""Covers: DP-1, DP-6, CP-4, CP-8, E0-3."""
import pytest

from common.config import ComplianceConfigError, Settings, validate_compliance
from common.llm import ProviderInfo


def info(name="local", external=False, retains=False, baa=False):
    return ProviderInfo(name=name, kind="fake", base_url="", model="m", api_key_env="", external=external,
                        baa_signed=baa, retains_data=retains, region="local", max_concurrency=2)


def test_profile_defaults_lite(monkeypatch):
    s = Settings(_env_file=None)
    assert s.deployment_profile == "lite"
    assert (s.embed_provider, s.llm_provider, s.blob_provider, s.run_mode) == ("hashing", "none", "local", "all")


def test_profile_defaults_hybrid():
    s = Settings(_env_file=None, deployment_profile="hybrid")
    assert s.embed_provider == "minilm"
    assert s.external_max_classification == "internal"


def test_env_overrides_profile(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "airgapped")
    monkeypatch.setenv("EMBED_PROVIDER", "hashing")
    s = Settings(_env_file=None)
    assert s.llm_provider == "local-ollama"
    assert s.embed_provider == "hashing"


def test_airgapped_refuses_external_provider():
    s = Settings(_env_file=None, deployment_profile="airgapped", llm_provider="openrouter-free")
    with pytest.raises(ComplianceConfigError, match="air-gapped"):
        validate_compliance(s, {"openrouter-free": info("openrouter-free", external=True, retains=True)})


def test_retaining_provider_requires_synthetic():
    s = Settings(_env_file=None, deployment_profile="hybrid", llm_provider="openrouter-free",
                 synthetic_data_only=False, database_url="postgresql://x/y?sslmode=require")
    with pytest.raises(ComplianceConfigError, match="synthetic"):
        validate_compliance(s, {"openrouter-free": info("openrouter-free", external=True, retains=True)})


def test_non_baa_provider_requires_synthetic():
    s = Settings(_env_file=None, deployment_profile="hybrid", llm_provider="azure-openai",
                 synthetic_data_only=False, database_url="postgresql://x/y?sslmode=require")
    with pytest.raises(ComplianceConfigError, match="BAA"):
        validate_compliance(s, {"azure-openai": info("azure-openai", external=True)})


def test_cloud_requires_sslmode():
    s = Settings(_env_file=None, deployment_profile="cloud", llm_provider="none",
                 database_url="postgresql://u:p@db/x")
    with pytest.raises(ComplianceConfigError, match="sslmode"):
        validate_compliance(s, {})


def test_unknown_provider_rejected():
    s = Settings(_env_file=None, llm_provider="nope")
    with pytest.raises(ComplianceConfigError, match="Unknown LLM provider"):
        validate_compliance(s, {})


def test_lite_defaults_pass():
    validate_compliance(Settings(_env_file=None), {})


def test_config_view_masks_secrets():
    s = Settings(_env_file=None, database_url="postgresql://user:hunter2@db/x", oidc_client_secret="abc")
    view = s.public_view()
    assert "hunter2" not in str(view)
    assert view["oidc_client_secret"] == "***"
    assert view["deployment_profile"] == "lite"


def test_min_relevance_follows_embedder():
    """Calibrated in docs/RESULTS.md: hashing scores run lower than MiniLM."""
    assert Settings(_env_file=None).min_relevance == 0.15
    assert Settings(_env_file=None, deployment_profile="hybrid").min_relevance == 0.35
    assert Settings(_env_file=None, min_relevance=0.5).min_relevance == 0.5
