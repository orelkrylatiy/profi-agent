"""Резолв PROFI_CHROME_PROFILE: относительные пути — от корня проекта (config)."""

import importlib

import pytest


@pytest.fixture
def restore_config():
    """reload(config) мутирует общий объект модуля — после теста возвращаем как было."""
    import profi.config as config

    yield config
    importlib.reload(config)


def test_relative_profile_resolved_from_project_root(restore_config, monkeypatch):
    config = restore_config
    monkeypatch.setenv("PROFI_CHROME_PROFILE", "data/browser-profiles/lang")
    importlib.reload(config)
    assert config.USER_DATA_DIR == config.PROJECT_DIR / "data" / "browser-profiles" / "lang"


def test_absolute_profile_kept(restore_config, monkeypatch, tmp_path):
    config = restore_config
    monkeypatch.setenv("PROFI_CHROME_PROFILE", str(tmp_path / "abs-profile"))
    importlib.reload(config)
    assert config.USER_DATA_DIR == tmp_path / "abs-profile"


def test_default_mac_profile_without_env(restore_config, monkeypatch):
    config = restore_config
    monkeypatch.delenv("PROFI_CHROME_PROFILE", raising=False)
    importlib.reload(config)
    assert config.USER_DATA_DIR == config.PROJECT_DIR / "data" / "chrome-profiles" / "main"


def test_project_dir_is_repo_root(restore_config):
    config = restore_config
    assert (config.PROJECT_DIR / "pyproject.toml").exists()
    assert (config.PROJECT_DIR / "personas" / "info.md").exists()
