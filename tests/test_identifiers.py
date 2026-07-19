import pytest

from aromanexus.identifiers import (
    clean_text,
    is_valid_cas,
    normalize_cas,
    require_valid_cas,
)


@pytest.mark.parametrize("cas", ["100-52-7", "64-17-5", "7732-18-5", "5989-54-8"])
def test_valid_cas_checksums(cas):
    assert is_valid_cas(cas)


def test_normalizes_digits_and_unicode_spacing():
    assert normalize_cas(" 100527 ") == "100-52-7"
    assert normalize_cas("\u00a0100-52-7\u00a0") == "100-52-7"


def test_rejects_bad_checksum_and_sentinels():
    assert not is_valid_cas("100-52-8")
    assert clean_text("\\") == ""
    with pytest.raises(ValueError, match="checksum"):
        require_valid_cas("100-52-8")
