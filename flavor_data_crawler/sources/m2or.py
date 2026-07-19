"""Pinned, cache-backed access to the M2OR odorant/receptor snapshot."""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import requests

from flavor_data_crawler.identifiers import normalize_cas, require_valid_cas
from flavor_data_crawler.models import LookupResult

M2OR_VERSION = "b5cf2f1714b28e591b07539559363d0a6205cf2a"
M2OR_FILENAME = "M2OR_20230428.csv"
M2OR_REPOSITORY_URL = "https://github.com/chemosim-lab/M2OR"
M2OR_DATA_URL = (
    f"https://raw.githubusercontent.com/chemosim-lab/M2OR/{M2OR_VERSION}/{M2OR_FILENAME}"
)
M2OR_LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0"

DownloadFunction = Callable[[str, Path], bytes | str | None]


def _default_cache_dir() -> Path:
    configured = os.environ.get("FLAVOR_DATA_CRAWLER_CACHE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "flavor-data-crawler"


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _is_responsive(value: object) -> bool:
    return _clean(value).casefold() in {"1", "true", "yes", "responsive", "agonist"}


def _canonical_doi(value: object) -> str:
    doi = _clean(value)
    if not doi:
        return ""
    doi = re.sub(r"^doi\s*:\s*", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.strip()


def _sorted_join(values: Iterable[str]) -> str:
    unique = {_clean(value) for value in values if _clean(value)}
    return "; ".join(sorted(unique, key=str.casefold))


class M2ORClient:
    """Query an exact normalized CAS number in the pinned M2OR CSV.

    The large upstream CSV is not distributed with this package. It is read
    from ``data_path`` when supplied, otherwise cached below ``cache_dir`` and
    downloaded on first use when ``allow_download`` is true. ``rows`` offers a
    lightweight injection point for callers and offline tests.
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        *,
        data_path: str | Path | None = None,
        allow_download: bool = True,
        data_url: str = M2OR_DATA_URL,
        timeout: float = 120,
        session: requests.Session | None = None,
        downloader: DownloadFunction | None = None,
        rows: Iterable[Mapping[str, object]] | None = None,
    ) -> None:
        root = Path(cache_dir).expanduser() if cache_dir else _default_cache_dir()
        self.data_path = (
            Path(data_path).expanduser()
            if data_path is not None
            else root / "m2or" / M2OR_VERSION / M2OR_FILENAME
        )
        self.allow_download = allow_download
        self.data_url = data_url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.downloader = downloader
        self._rows = tuple(dict(row) for row in rows) if rows is not None else None

    def lookup_cas(self, cas: object) -> LookupResult:
        """Aggregate receptor-pair evidence for one exact normalized CAS."""

        try:
            normalized_cas = require_valid_cas(cas)
        except ValueError as exc:
            return self._result(status="invalid_input", message=str(exc))

        try:
            if self._rows is not None:
                rows: Iterable[Mapping[str, object]] = self._rows
                cache_hit = False
            else:
                cache_hit = self._ensure_data_file()
                rows = self._iter_rows()
            values = self._aggregate(rows, normalized_cas)
        except FileNotFoundError as exc:
            return self._result(status="missing_data", message=str(exc))
        except requests.RequestException as exc:
            return self._result(status="network_error", message=str(exc))
        except (OSError, csv.Error, UnicodeError, ValueError) as exc:
            return self._result(status="parse_error", message=str(exc))

        if values["M2OR Pair Count"] == 0:
            return self._result(
                values=values,
                status="not_found",
                message=f"No exact M2OR CAS match for {normalized_cas}",
                cache_hit=cache_hit,
            )
        return self._result(values=values, cache_hit=cache_hit)

    def _aggregate(
        self,
        rows: Iterable[Mapping[str, object]],
        normalized_cas: str,
    ) -> dict[str, Any]:
        pairs: set[tuple[str, ...]] = set()
        responsive_pairs: set[tuple[str, ...]] = set()
        species: set[str] = set()
        human_receptors: set[str] = set()
        dois: set[str] = set()

        for row in rows:
            row_cas = normalize_cas(row.get("CAS"))
            if row_cas != normalized_cas:
                continue

            pair_key = self._pair_key(row)
            pairs.add(pair_key)
            responsive = _is_responsive(row.get("Responsive"))
            if responsive:
                responsive_pairs.add(pair_key)

            row_species = _clean(row.get("species") or row.get("Species"))
            if row_species:
                species.add(row_species)

            if responsive and row_species.casefold() == "homo sapiens":
                receptor = _clean(
                    row.get("Gene ID")
                    or row.get("Gene Name")
                    or row.get("Uniprot ID")
                    or row.get("Sequence")
                )
                mutation = _clean(row.get("Mutation"))
                if receptor:
                    human_receptors.add(f"{receptor} ({mutation})" if mutation else receptor)

            doi = _canonical_doi(row.get("DOI"))
            if doi:
                dois.add(doi)

        return {
            "M2OR Pair Count": len(pairs),
            "M2OR Responsive Count": len(responsive_pairs),
            "M2OR Species": _sorted_join(species),
            "M2OR Human Responsive Receptors": _sorted_join(human_receptors),
            "M2OR DOIs": _sorted_join(dois),
        }

    @staticmethod
    def _pair_key(row: Mapping[str, object]) -> tuple[str, ...]:
        species = _clean(row.get("species") or row.get("Species")).casefold()
        mutation = _clean(row.get("Mutation")).upper()
        sequence = re.sub(r"\s+", "", _clean(row.get("Sequence"))).upper()
        uniprot = _clean(row.get("Uniprot ID")).upper()
        gene = _clean(row.get("Gene ID") or row.get("Gene Name")).upper()
        if sequence:
            receptor_type, receptor = "sequence", sequence
        elif uniprot:
            receptor_type, receptor = "uniprot", uniprot
        elif gene:
            receptor_type, receptor = "gene", gene
        else:
            # A source row without any receptor identifier cannot be safely
            # merged with another unidentified experiment.
            receptor_type = "record"
            receptor = _clean(row.get("id") or row.get("ID"))
        return (
            "pair",
            species,
            receptor_type,
            receptor,
            mutation,
        )

    def _iter_rows(self) -> Iterable[Mapping[str, object]]:
        with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            if not reader.fieldnames or "CAS" not in reader.fieldnames:
                raise csv.Error("M2OR CSV is missing its semicolon-delimited CAS column")
            yield from reader

    def _ensure_data_file(self) -> bool:
        if self.data_path.is_file() and self.data_path.stat().st_size:
            return True
        if not self.allow_download:
            raise FileNotFoundError(
                f"{M2OR_FILENAME} is not cached and downloads are disabled ({self.data_path})"
            )

        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.data_path.with_name(f".{self.data_path.name}.{os.getpid()}.part")
        temporary.unlink(missing_ok=True)
        try:
            if self.downloader is not None:
                payload = self.downloader(self.data_url, temporary)
                if isinstance(payload, str):
                    temporary.write_text(payload, encoding="utf-8")
                elif isinstance(payload, bytes):
                    temporary.write_bytes(payload)
            else:
                response = self.session.get(self.data_url, timeout=self.timeout, stream=True)
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if not temporary.is_file() or not temporary.stat().st_size:
                raise OSError(f"Downloader produced no data for {self.data_url}")
            temporary.replace(self.data_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return False

    def _result(
        self,
        *,
        values: dict[str, Any] | None = None,
        status: str = "ok",
        message: str = "",
        cache_hit: bool = False,
    ) -> LookupResult:
        return LookupResult(
            provider="M2OR",
            values=values or {},
            source_url=self.data_url,
            status=status,
            message=message,
            cache_hit=cache_hit,
            version=M2OR_VERSION,
            license_url=M2OR_LICENSE_URL,
        )


__all__ = ["M2OR_DATA_URL", "M2OR_VERSION", "M2ORClient"]
