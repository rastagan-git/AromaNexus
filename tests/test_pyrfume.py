from __future__ import annotations

from pathlib import Path

from aromanexus.sources.pyrfume import (
    ARCHIVE_FILES,
    PYRFUME_DATA_VERSION,
    PyrfumeArchiveClient,
)

SYNTHETIC_ARCHIVE_FILES = {
    "aromadb/manifest.toml": """
[source]
doi = "10.0000/example-aromadb"
title = "Synthetic Aroma Archive"
authors = "Example Authors"
extra = "Copyright remains with the Example Aroma Consortium"

[raw]
LICENSE = "Consult the source owner before reuse"
""".lstrip(),
    "aromadb/molecules.csv": (
        "CID,MolecularWeight,IsomericSMILES,IUPACName,name\n"
        "176,60.05,CC(=O)O,acetic acid,synthetic vinegar molecule\n"
    ),
    "aromadb/stimuli.csv": "Stimulus,CID\nstimulus-a,176\n",
    "aromadb/behavior.csv": (
        "Stimulus,Raw Descriptors,Filtered Descriptors,Modifiers\n"
        'stimulus-a,"sharp, sour","sour, pungent",\n'
    ),
    "flavornet/manifest.toml": """
[source]
url = "https://example.test/flavornet"
title = "Synthetic Flavor Archive"
authors = "Test Curators"
extra = "Example archive copyright notice"

[raw]
""".lstrip(),
    "flavornet/molecules.csv": (
        "CID,MolecularWeight,IsomericSMILES,IUPACName,name\n"
        "176,60.05,CC(=O)O,acetic acid,synthetic acetic acid\n"
    ),
    "flavornet/stimuli.csv": "Stimulus,CID\n176,176\n",
    "flavornet/behavior.csv": "Stimulus,Descriptors\n176,sour;acidic\n",
    "superscent/manifest.toml": """
[source]
url = "https://example.test/superscent"
title = "Synthetic SuperScent List"
authors = ""
extra = ""

[raw]
LICENSE = ""
""".lstrip(),
    "superscent/molecules.csv": (
        "CID,MolecularWeight,IsomericSMILES,IUPACName,name\n"
        "176,60.05,CC(=O)O,acetic acid,synthetic super molecule\n"
    ),
}


def _synthetic_downloader(url: str, _destination: Path) -> bytes:
    archive_file = "/".join(url.split("/")[-2:])
    return SYNTHETIC_ARCHIVE_FILES[archive_file].encode("utf-8")


def test_lookup_downloads_allowlisted_files_and_reuses_cache(tmp_path: Path) -> None:
    client = PyrfumeArchiveClient(cache_dir=tmp_path, downloader=_synthetic_downloader)

    result = client.lookup("176.0")

    assert result.status == "ok"
    assert result.cache_hit is False
    assert result.version == PYRFUME_DATA_VERSION
    assert result.values["Pyrfume Archives Matched"] == "aromadb; flavornet; superscent"
    assert result.values["Pyrfume aromadb Present"] is True
    assert result.values["Pyrfume aromadb Descriptors"] == "sour; pungent"
    assert result.values["Pyrfume flavornet Descriptors"] == "sour; acidic"
    assert result.values["Pyrfume superscent Present"] is True
    assert result.values["Pyrfume superscent Descriptors"] == ""
    assert result.values["Pyrfume aromadb Source Notes"] == (
        "Copyright remains with the Example Aroma Consortium"
    )
    assert result.values["Pyrfume aromadb License Note"] == (
        "Consult the source owner before reuse"
    )

    snapshot_cache = tmp_path / "pyrfume-data" / PYRFUME_DATA_VERSION
    expected = {
        snapshot_cache / archive / filename
        for archive, filenames in ARCHIVE_FILES.items()
        for filename in filenames
    }
    assert all(path.is_file() for path in expected)

    offline = PyrfumeArchiveClient(cache_dir=tmp_path, allow_download=False)
    cached_result = offline.lookup(176)
    assert cached_result.status == "ok"
    assert cached_result.cache_hit is True
    assert cached_result.values == result.values


def test_lookup_is_exact_and_can_select_one_archive(tmp_path: Path) -> None:
    client = PyrfumeArchiveClient(cache_dir=tmp_path, downloader=_synthetic_downloader)

    result = client.lookup(17, archives="aromadb")

    assert result.status == "not_found"
    assert result.values["Pyrfume aromadb Present"] is False
    assert result.values["Pyrfume Archives Matched"] == ""
    assert not (tmp_path / "pyrfume-data" / PYRFUME_DATA_VERSION / "flavornet").exists()


def test_lookup_rejects_invalid_cid_and_non_allowlisted_archive(tmp_path: Path) -> None:
    client = PyrfumeArchiveClient(cache_dir=tmp_path, allow_download=False)

    assert client.lookup("not-a-cid").status == "invalid_input"
    unsupported = client.lookup(176, archives=["not-reviewed"])
    assert unsupported.status == "invalid_input"
    assert "allowed: aromadb, flavornet, superscent" in unsupported.message
