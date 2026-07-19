"""Pinned, cache-backed access to a small set of Pyrfume data archives.

The adapter deliberately downloads data at run time instead of redistributing
Pyrfume archive files.  Each archive keeps its own source and rights notes from
``manifest.toml``; the Pyrfume repository must not be treated as granting one
blanket license for every upstream dataset.
"""

from __future__ import annotations

import csv
import os
import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import requests

from aromanexus.cache import default_cache_root
from aromanexus.models import LookupResult

PYRFUME_DATA_VERSION = "8054ea98ed675005ec10e67359902f500e4911b0"
PYRFUME_REPOSITORY_URL = "https://github.com/pyrfume/pyrfume-data"
PYRFUME_SNAPSHOT_URL = f"{PYRFUME_REPOSITORY_URL}/tree/{PYRFUME_DATA_VERSION}"
PYRFUME_RAW_BASE_URL = (
    f"https://raw.githubusercontent.com/pyrfume/pyrfume-data/{PYRFUME_DATA_VERSION}"
)

# Keep this list intentionally small and review additions archive-by-archive.
# SuperScent has no standardized stimuli.csv or behavior.csv in this snapshot.
ARCHIVE_FILES: dict[str, tuple[str, ...]] = {
    "aromadb": ("manifest.toml", "molecules.csv", "stimuli.csv", "behavior.csv"),
    "flavornet": ("manifest.toml", "molecules.csv", "stimuli.csv", "behavior.csv"),
    "superscent": ("manifest.toml", "molecules.csv"),
}
DEFAULT_ARCHIVES = tuple(ARCHIVE_FILES)

DownloadFunction = Callable[[str, Path], bytes | str | None]


def _default_cache_dir() -> Path:
    return default_cache_root()


def _normalize_cid(value: object) -> str:
    """Return a canonical positive PubChem CID, or raise ``ValueError``."""

    if value is None or isinstance(value, bool):
        raise ValueError("PubChem CID is empty")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text or not text.isdigit() or int(text) <= 0:
        raise ValueError(f"Invalid PubChem CID: {text or value!s}")
    return str(int(text))


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _unique_join(values: Iterable[str]) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return "; ".join(result)


def _descriptor_values(row: Mapping[str, object]) -> list[str]:
    for column in ("Filtered Descriptors", "Descriptors", "Raw Descriptors"):
        raw = _clean(row.get(column))
        if raw:
            return [part.strip() for part in re.split(r"[;,]", raw) if part.strip()]
    return []


class PyrfumeArchiveClient:
    """Query selected Pyrfume archives by exact PubChem CID.

    Parameters are intentionally injectable for offline use. ``cache_dir``
    controls the persistent cache root, ``base_url`` can target a mirror, and
    ``downloader`` may write synthetic test data to the supplied destination.
    A downloader may alternatively return ``bytes`` or ``str``.
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        *,
        base_url: str = PYRFUME_RAW_BASE_URL,
        allow_download: bool = True,
        timeout: float = 30,
        session: requests.Session | None = None,
        downloader: DownloadFunction | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else _default_cache_dir()
        self.base_url = base_url.rstrip("/")
        self.allow_download = allow_download
        self.timeout = timeout
        self.session = session or requests.Session()
        self.downloader = downloader

    def lookup(
        self,
        cid: object,
        archives: Iterable[str] | str | None = None,
    ) -> LookupResult:
        """Look up one CID across the requested allowlisted archives."""

        try:
            normalized_cid = _normalize_cid(cid)
            selected = self._select_archives(archives)
        except ValueError as exc:
            return self._result(status="invalid_input", message=str(exc))

        values: dict[str, Any] = {}
        matched: list[str] = []
        errors: list[str] = []
        cache_states: list[bool] = []

        for archive in selected:
            prefix = f"Pyrfume {archive}"
            try:
                paths: dict[str, Path] = {}
                for filename in ARCHIVE_FILES[archive]:
                    path, cache_hit = self._ensure_file(archive, filename)
                    paths[filename] = path
                    cache_states.append(cache_hit)

                manifest = self._read_manifest(paths["manifest.toml"])
                source = manifest.get("source", {})
                if not isinstance(source, Mapping):
                    source = {}
                raw_section = manifest.get("raw", {})
                if not isinstance(raw_section, Mapping):
                    raw_section = {}

                values.update(
                    {
                        f"{prefix} Source Title": _clean(source.get("title")),
                        f"{prefix} Source Reference": _clean(
                            source.get("doi") or source.get("url")
                        ),
                        f"{prefix} Source Authors": _clean(source.get("authors")),
                        # Keep copyright and usage caveats verbatim from the manifest.
                        f"{prefix} Source Notes": _clean(source.get("extra")),
                        f"{prefix} License Note": _clean(raw_section.get("LICENSE")),
                        f"{prefix} Manifest URL": self._source_url(archive, "manifest.toml"),
                    }
                )

                molecule_rows = self._read_csv(paths["molecules.csv"])
                molecules = [
                    row for row in molecule_rows if self._row_cid(row.get("CID")) == normalized_cid
                ]
                present = bool(molecules)
                values[f"{prefix} Present"] = present
                values[f"{prefix} Name"] = _unique_join(
                    _clean(row.get("name") or row.get("Name")) for row in molecules
                )
                values[f"{prefix} IUPAC Name"] = _unique_join(
                    _clean(row.get("IUPACName") or row.get("IUPAC Name")) for row in molecules
                )

                descriptors: list[str] = []
                if present and "behavior.csv" in paths:
                    stimulus_ids = {normalized_cid}
                    if "stimuli.csv" in paths:
                        stimulus_ids.update(
                            _clean(row.get("Stimulus"))
                            for row in self._read_csv(paths["stimuli.csv"])
                            if self._row_cid(row.get("CID")) == normalized_cid
                        )
                    for row in self._read_csv(paths["behavior.csv"]):
                        if _clean(row.get("Stimulus")) in stimulus_ids:
                            descriptors.extend(_descriptor_values(row))
                values[f"{prefix} Descriptors"] = _unique_join(descriptors)

                if present:
                    matched.append(archive)
            except FileNotFoundError as exc:
                values[f"{prefix} Present"] = False
                values[f"{prefix} Descriptors"] = ""
                errors.append(f"{archive}: {exc}")
            except (OSError, csv.Error, tomllib.TOMLDecodeError, UnicodeError) as exc:
                values[f"{prefix} Present"] = False
                values[f"{prefix} Descriptors"] = ""
                errors.append(f"{archive}: could not parse cached data ({exc})")
            except requests.RequestException as exc:
                values[f"{prefix} Present"] = False
                values[f"{prefix} Descriptors"] = ""
                errors.append(f"{archive}: download failed ({exc})")

        values["Pyrfume Archives Matched"] = "; ".join(matched)
        if errors:
            status = "partial" if len(errors) < len(selected) else "data_error"
            message = "; ".join(errors)
        elif not matched:
            status = "not_found"
            message = f"CID {normalized_cid} was not found in {', '.join(selected)}"
        else:
            status = "ok"
            message = ""
        return self._result(
            values=values,
            status=status,
            message=message,
            cache_hit=bool(cache_states) and all(cache_states),
        )

    @staticmethod
    def _select_archives(archives: Iterable[str] | str | None) -> tuple[str, ...]:
        if archives is None:
            requested: Iterable[str] = DEFAULT_ARCHIVES
        elif isinstance(archives, str):
            requested = [archives]
        else:
            requested = archives
        selected: list[str] = []
        for archive in requested:
            normalized = str(archive).strip().casefold()
            if normalized not in ARCHIVE_FILES:
                allowed = ", ".join(DEFAULT_ARCHIVES)
                raise ValueError(f"Unsupported Pyrfume archive {archive!r}; allowed: {allowed}")
            if normalized not in selected:
                selected.append(normalized)
        if not selected:
            raise ValueError("At least one Pyrfume archive must be selected")
        return tuple(selected)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            return tomllib.load(handle)

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise csv.Error(f"CSV has no header: {path}")
            return list(reader)

    @staticmethod
    def _row_cid(value: object) -> str:
        try:
            return _normalize_cid(value)
        except ValueError:
            return ""

    def _cache_path(self, archive: str, filename: str) -> Path:
        return self.cache_dir / "pyrfume-data" / PYRFUME_DATA_VERSION / archive / filename

    def _source_url(self, archive: str, filename: str) -> str:
        return f"{self.base_url}/{archive}/{filename}"

    def _ensure_file(self, archive: str, filename: str) -> tuple[Path, bool]:
        destination = self._cache_path(archive, filename)
        if destination.is_file() and destination.stat().st_size:
            return destination, True
        if not self.allow_download:
            raise FileNotFoundError(
                f"{filename} is not cached and downloads are disabled ({destination})"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
        temporary.unlink(missing_ok=True)
        try:
            url = self._source_url(archive, filename)
            if self.downloader is not None:
                payload = self.downloader(url, temporary)
                if isinstance(payload, str):
                    temporary.write_text(payload, encoding="utf-8")
                elif isinstance(payload, bytes):
                    temporary.write_bytes(payload)
            else:
                response = self.session.get(url, timeout=self.timeout, stream=True)
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            handle.write(chunk)
            if not temporary.is_file() or not temporary.stat().st_size:
                raise OSError(f"Downloader produced no data for {url}")
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return destination, False

    @staticmethod
    def _result(
        *,
        values: dict[str, Any] | None = None,
        status: str = "ok",
        message: str = "",
        cache_hit: bool = False,
    ) -> LookupResult:
        return LookupResult(
            provider="Pyrfume",
            values=values or {},
            source_url=PYRFUME_SNAPSHOT_URL,
            status=status,
            message=message,
            cache_hit=cache_hit,
            version=PYRFUME_DATA_VERSION,
            # Rights differ by archive; manifest fields are returned per archive.
            license_url="",
        )


__all__ = [
    "ARCHIVE_FILES",
    "DEFAULT_ARCHIVES",
    "PYRFUME_DATA_VERSION",
    "PyrfumeArchiveClient",
]
