from pathlib import Path

import pytest

from profi.profiles import load_profile


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"


def test_info_profile_loads():
    profile = load_profile("info", PROFILES)
    assert profile.persona == "info"
    assert "информатик" in profile.subject_keywords
    assert profile.remote_only is True
    assert profile.fallback_enabled is True
    assert profile.fallback_templates


def test_languages_combines_english_and_spanish():
    profile = load_profile("languages", PROFILES)
    assert profile.persona == "lang"
    assert "английск" in profile.subject_keywords
    assert "испанск" in profile.subject_keywords
    assert "star-метод" in profile.stop_patterns


def test_explicit_missing_profile_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="profile not found"):
        load_profile("missing", tmp_path)


def test_invalid_profile_name_is_rejected():
    with pytest.raises(ValueError, match="invalid profile name"):
        load_profile("../info", PROFILES)
