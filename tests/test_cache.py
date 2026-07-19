from pathlib import Path

from aromanexus.cache import default_cache_root, default_http_cache_dir


def test_primary_cache_environment_applies_to_all_providers(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AROMANEXUS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FLAVOR_DATA_CACHE_DIR", str(tmp_path / "old-http"))
    monkeypatch.setenv("FLAVOR_DATA_CRAWLER_CACHE", str(tmp_path / "old-root"))

    assert default_cache_root() == tmp_path
    assert default_http_cache_dir() == tmp_path / "http"


def test_legacy_cache_environments_remain_supported(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AROMANEXUS_CACHE_DIR", raising=False)
    monkeypatch.setenv("FLAVOR_DATA_CRAWLER_CACHE", str(tmp_path / "old-root"))
    monkeypatch.setenv("FLAVOR_DATA_CACHE_DIR", str(tmp_path / "old-http"))

    assert default_cache_root() == tmp_path / "old-root"
    assert default_http_cache_dir() == tmp_path / "old-http"
