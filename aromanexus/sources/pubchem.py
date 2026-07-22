"""PubChem PUG REST properties and PUG-View odor annotations."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aromanexus.http import (
    DEFAULT_CACHE_DIR,
    CachedHttpClient,
    HttpClientError,
    HttpResponse,
)
from aromanexus.identifiers import clean_text, is_valid_cas, normalize_cas
from aromanexus.models import LookupResult

PUBCHEM_PUG_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PUBCHEM_LICENSE_URL = "https://www.ncbi.nlm.nih.gov/home/about/policies/"
PUBCHEM_PUG_REST_VERSION = "PUG REST"
PUBCHEM_PUG_VIEW_VERSION = "PUG REST + PUG-View"
PUBCHEM_VERSION = PUBCHEM_PUG_VIEW_VERSION
PROPERTY_TAGS = (
    "Title",
    "IUPACName",
    "MolecularFormula",
    "MolecularWeight",
    "CanonicalSMILES",
    "IsomericSMILES",
    "InChI",
    "InChIKey",
    "XLogP",
)


def _first_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0]
    return None


def parse_pubchem_properties(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the first PUG REST property record into stable local field names."""

    table = payload.get("PropertyTable")
    if not isinstance(table, Mapping):
        return {}
    record = _first_mapping(table.get("Properties"))
    if record is None or "CID" not in record:
        return {}

    # PubChem now returns SMILES/ConnectivitySMILES for the legacy request tags.
    # Supporting both spellings keeps cached and current API responses compatible.
    return {
        "cid": record.get("CID"),
        "title": record.get("Title", ""),
        "iupac_name": record.get("IUPACName", ""),
        "molecular_formula": record.get("MolecularFormula", ""),
        "molecular_weight": record.get("MolecularWeight", ""),
        "canonical_smiles": record.get("ConnectivitySMILES", record.get("CanonicalSMILES", "")),
        "isomeric_smiles": record.get("SMILES", record.get("IsomericSMILES", "")),
        "inchi": record.get("InChI", ""),
        "inchikey": record.get("InChIKey", ""),
        "xlogp": record.get("XLogP", ""),
    }


def parse_pubchem_identifiers(payload: Mapping[str, Any]) -> list[str]:
    """Extract unique, valid CAS identifiers from a PUG REST identifiers result."""

    information_list = payload.get("InformationList")
    if not isinstance(information_list, Mapping):
        return []
    information = information_list.get("Information")
    if not isinstance(information, list):
        return []

    cas_numbers: list[str] = []
    for item in information:
        if not isinstance(item, Mapping):
            continue
        identifiers = item.get("Identifiers")
        if not isinstance(identifiers, list):
            continue
        for identifier in identifiers:
            if not isinstance(identifier, Mapping):
                continue
            if str(identifier.get("Type", "")).casefold() != "cas":
                continue
            cas = normalize_cas(identifier.get("Identifier"))
            if is_valid_cas(cas) and cas not in cas_numbers:
                cas_numbers.append(cas)
    return cas_numbers


def parse_pubchem_synonyms(payload: Mapping[str, Any]) -> list[str]:
    """Extract de-duplicated compound synonyms from PUG REST JSON."""

    information_list = payload.get("InformationList")
    if not isinstance(information_list, Mapping):
        return []
    information = information_list.get("Information")
    if not isinstance(information, list):
        return []

    synonyms: list[str] = []
    for item in information:
        if not isinstance(item, Mapping):
            continue
        raw_synonyms = item.get("Synonym")
        if not isinstance(raw_synonyms, list):
            continue
        for raw in raw_synonyms:
            synonym = clean_text(raw)
            if synonym and synonym not in synonyms:
                synonyms.append(synonym)
    return synonyms


def _walk_sections(sections: object) -> Iterable[Mapping[str, Any]]:
    if not isinstance(sections, list):
        return
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        yield section
        yield from _walk_sections(section.get("Section"))


def _value_strings(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    strings: list[str] = []
    markup = value.get("StringWithMarkup")
    if isinstance(markup, list):
        for item in markup:
            if isinstance(item, Mapping):
                text = clean_text(item.get("String"))
                if text:
                    strings.append(text)
    direct = clean_text(value.get("String"))
    if direct:
        strings.append(direct)
    return strings


def _reference_numbers(information: Mapping[str, Any]) -> list[str]:
    raw = information.get("ReferenceNumber")
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [str(value) for value in values]


def _append_unique(items: list[str], value: object) -> None:
    text = clean_text(value)
    if text and text not in items:
        items.append(text)


def parse_pubchem_odor(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten PUG-View Odor text while retaining contributor provenance."""

    record = payload.get("Record")
    if not isinstance(record, Mapping):
        return {
            "odor": [],
            "odor_annotations": [],
            "odor_sources": [],
            "odor_source_urls": [],
            "odor_license_urls": [],
        }

    references: dict[str, Mapping[str, Any]] = {}
    raw_references = record.get("Reference")
    if isinstance(raw_references, list):
        for reference in raw_references:
            if isinstance(reference, Mapping) and reference.get("ReferenceNumber") is not None:
                references[str(reference["ReferenceNumber"])] = reference

    odors: list[str] = []
    annotations: list[dict[str, Any]] = []
    source_names: list[str] = []
    source_urls: list[str] = []
    license_urls: list[str] = []

    for section in _walk_sections(record.get("Section")):
        if str(section.get("TOCHeading", "")).strip().casefold() != "odor":
            continue
        information_items = section.get("Information")
        if not isinstance(information_items, list):
            continue
        for information in information_items:
            if not isinstance(information, Mapping):
                continue
            texts = _value_strings(information.get("Value"))
            reference_numbers = _reference_numbers(information) or [""]
            for text in texts:
                _append_unique(odors, text)
                for number in reference_numbers:
                    reference = references.get(number, {})
                    source_name = clean_text(reference.get("SourceName"))
                    source_url = clean_text(reference.get("URL"))
                    license_url = clean_text(reference.get("LicenseURL"))
                    annotation = {
                        "text": text,
                        "reference_number": number,
                        "source_name": source_name,
                        "source_url": source_url,
                        "license_url": license_url,
                    }
                    if annotation not in annotations:
                        annotations.append(annotation)
                    _append_unique(source_names, source_name)
                    _append_unique(source_urls, source_url)
                    _append_unique(license_urls, license_url)

    return {
        "odor": odors,
        "odor_annotations": annotations,
        "odor_sources": source_names,
        "odor_source_urls": source_urls,
        "odor_license_urls": license_urls,
    }


class PubChemClient:
    """Resolve names/CAS numbers through PUG REST and optional PUG-View odor data."""

    provider = "PubChem"

    def __init__(
        self,
        http_client: CachedHttpClient | Any | None = None,
        *,
        cache_dir: str | Path | None = DEFAULT_CACHE_DIR / "pubchem",
        min_interval: float = 0.25,
        timeout: float | tuple[float, float] = (5.0, 30.0),
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http = http_client or CachedHttpClient(
            cache_dir=cache_dir,
            min_interval=min_interval,
            timeout=timeout,
            session=session,
            sleep=sleep,
        )

    def lookup(self, identifier: object, include_odor: bool = True) -> LookupResult:
        """Look up a CAS number or compound name and return normalized properties."""

        query = clean_text(identifier)
        if not query:
            return self._failure(status="invalid_input", message="Compound identifier is empty.")

        encoded_query = quote(query, safe="")
        properties_url = (
            f"{PUBCHEM_PUG_BASE}/compound/name/{encoded_query}/property/"
            f"{','.join(PROPERTY_TAGS)}/JSON"
        )
        try:
            properties_response = self.http.get(
                properties_url,
                headers={"Accept": "application/json"},
            )
        except HttpClientError as exc:
            return self._failure(status="network_error", message=str(exc), source_url=exc.url)

        if properties_response.status_code == 404:
            return self._response_failure(
                properties_response,
                status="not_found",
                message=f"PubChem did not resolve {query!r}.",
            )
        if not properties_response.ok:
            return self._response_failure(
                properties_response,
                status="http_error",
                message=f"PubChem returned HTTP {properties_response.status_code}.",
            )
        try:
            properties_payload = properties_response.json()
        except (json.JSONDecodeError, TypeError) as exc:
            return self._response_failure(
                properties_response,
                status="parse_error",
                message=f"PubChem properties response was not valid JSON: {exc}",
            )
        if not isinstance(properties_payload, Mapping):
            properties = {}
        else:
            properties = parse_pubchem_properties(properties_payload)
        if not properties or properties.get("cid") in (None, ""):
            return self._response_failure(
                properties_response,
                status="parse_error",
                message="PubChem properties response did not contain a CID.",
            )

        cid = properties["cid"]
        values: dict[str, Any] = {
            "query": query,
            **properties,
            "pubchem_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            "synonyms": [],
            "cas_numbers": [],
            "odor": [],
            "odor_annotations": [],
            "odor_sources": [],
            "odor_source_urls": [],
            "odor_license_urls": [],
        }
        responses = [properties_response]
        warnings: list[str] = []

        identifiers_url = f"{PUBCHEM_PUG_BASE}/compound/cid/{cid}/identifiers/JSON"
        try:
            identifiers_response = self.http.get(
                identifiers_url,
                params={"identifier_type": "CAS"},
                headers={"Accept": "application/json"},
            )
            responses.append(identifiers_response)
            if identifiers_response.ok:
                payload = identifiers_response.json()
                if isinstance(payload, Mapping):
                    values["cas_numbers"] = parse_pubchem_identifiers(payload)
            elif identifiers_response.status_code != 404:
                warnings.append(f"CAS identifiers returned HTTP {identifiers_response.status_code}")
        except (HttpClientError, json.JSONDecodeError, TypeError) as exc:
            warnings.append(f"CAS identifiers unavailable: {exc}")

        synonyms_url = f"{PUBCHEM_PUG_BASE}/compound/cid/{cid}/synonyms/JSON"
        try:
            synonyms_response = self.http.get(
                synonyms_url,
                headers={"Accept": "application/json"},
            )
            responses.append(synonyms_response)
            if synonyms_response.ok:
                payload = synonyms_response.json()
                if isinstance(payload, Mapping):
                    values["synonyms"] = parse_pubchem_synonyms(payload)
            elif synonyms_response.status_code != 404:
                warnings.append(f"Synonyms returned HTTP {synonyms_response.status_code}")
        except (HttpClientError, json.JSONDecodeError, TypeError) as exc:
            warnings.append(f"Synonyms unavailable: {exc}")

        normalized_query_cas = normalize_cas(query)
        if is_valid_cas(normalized_query_cas) and normalized_query_cas not in values["cas_numbers"]:
            values["cas_numbers"].insert(0, normalized_query_cas)
        for synonym in values["synonyms"]:
            synonym_cas = normalize_cas(synonym)
            if is_valid_cas(synonym_cas) and synonym_cas not in values["cas_numbers"]:
                values["cas_numbers"].append(synonym_cas)

        pug_view_attempted = False
        if include_odor:
            odor_url = f"{PUBCHEM_VIEW_BASE}/data/compound/{cid}/JSON"
            pug_view_attempted = True
            try:
                odor_response = self.http.get(
                    odor_url,
                    params={"heading": "Odor"},
                    headers={"Accept": "application/json"},
                )
                responses.append(odor_response)
                if odor_response.ok:
                    payload = odor_response.json()
                    if isinstance(payload, Mapping):
                        values.update(parse_pubchem_odor(payload))
                elif odor_response.status_code != 404:
                    warnings.append(f"Odor annotations returned HTTP {odor_response.status_code}")
            except (HttpClientError, json.JSONDecodeError, TypeError) as exc:
                warnings.append(f"Odor annotations unavailable: {exc}")

        return LookupResult(
            provider=self.provider,
            values=values,
            source_url=properties_response.url,
            retrieved_at=properties_response.metadata.retrieved_at,
            status="partial" if warnings else "ok",
            message="; ".join(warnings),
            cache_hit=all(response.metadata.cache_hit for response in responses),
            version=(PUBCHEM_PUG_VIEW_VERSION if pug_view_attempted else PUBCHEM_PUG_REST_VERSION),
            license_url=PUBCHEM_LICENSE_URL,
        )

    def _response_failure(
        self,
        response: HttpResponse,
        *,
        status: str,
        message: str,
    ) -> LookupResult:
        return LookupResult(
            provider=self.provider,
            status=status,
            message=message,
            source_url=response.url,
            retrieved_at=response.metadata.retrieved_at,
            cache_hit=response.metadata.cache_hit,
            version=PUBCHEM_PUG_REST_VERSION,
            license_url=PUBCHEM_LICENSE_URL,
        )

    def _failure(self, *, status: str, message: str, source_url: str = "") -> LookupResult:
        return LookupResult(
            provider=self.provider,
            status=status,
            message=message,
            source_url=source_url,
            retrieved_at="",
            version=PUBCHEM_PUG_REST_VERSION,
            license_url=PUBCHEM_LICENSE_URL,
        )


PubChemSource = PubChemClient

__all__ = [
    "PubChemClient",
    "PubChemSource",
    "parse_pubchem_identifiers",
    "parse_pubchem_odor",
    "parse_pubchem_properties",
    "parse_pubchem_synonyms",
]
