from __future__ import annotations

import json
from typing import Any

from aromanexus.http import HttpResponse, RetrievalMetadata
from aromanexus.sources.pubchem import (
    PubChemClient,
    parse_pubchem_identifiers,
    parse_pubchem_odor,
    parse_pubchem_properties,
    parse_pubchem_synonyms,
)

PROPERTIES = {
    "PropertyTable": {
        "Properties": [
            {
                "CID": 240,
                "Title": "Benzaldehyde",
                "IUPACName": "benzaldehyde",
                "MolecularFormula": "C7H6O",
                "MolecularWeight": "106.12",
                "ConnectivitySMILES": "C1=CC=C(C=C1)C=O",
                "SMILES": "C1=CC=C(C=C1)C=O",
                "InChI": "InChI=1S/C7H6O/c8-6-7-4-2-1-3-5-7/h1-6H",
                "InChIKey": "HUMNYLRZRPPJDN-UHFFFAOYSA-N",
                "XLogP": 1.5,
            }
        ]
    }
}

IDENTIFIERS = {
    "InformationList": {
        "Information": [
            {
                "CID": 240,
                "Identifiers": [
                    {"Type": "CAS", "Identifier": "100-52-7"},
                    {"Type": "CAS", "Identifier": "not-a-cas"},
                ],
            }
        ]
    }
}

SYNONYMS = {
    "InformationList": {
        "Information": [{"CID": 240, "Synonym": ["Benzaldehyde", "100-52-7", "Benzaldehyde"]}]
    }
}

ODOR = {
    "Record": {
        "RecordNumber": 240,
        "Section": [
            {
                "TOCHeading": "Chemical and Physical Properties",
                "Section": [
                    {
                        "TOCHeading": "Experimental Properties",
                        "Section": [
                            {
                                "TOCHeading": "Odor",
                                "Information": [
                                    {
                                        "ReferenceNumber": 126,
                                        "Value": {
                                            "StringWithMarkup": [
                                                {"String": "Characteristic almond odor"}
                                            ]
                                        },
                                    },
                                    {
                                        "ReferenceNumber": 126,
                                        "Value": {
                                            "StringWithMarkup": [
                                                {"String": "Odor of bitter almond"}
                                            ]
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "Reference": [
            {
                "ReferenceNumber": 126,
                "SourceName": "Hazardous Substances Data Bank (HSDB)",
                "URL": "https://pubchem.ncbi.nlm.nih.gov/source/hsdb/388",
                "LicenseURL": "https://www.nlm.nih.gov/web_policies.html",
            }
        ],
    }
}


def response(
    payload: object,
    *,
    status: int = 200,
    cache_hit: bool = True,
    url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/example",
) -> HttpResponse:
    return HttpResponse(
        status_code=status,
        text=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        metadata=RetrievalMetadata(
            requested_url=url,
            url=url,
            retrieved_at="2026-07-19T00:00:00+00:00",
            status_code=status,
            cache_hit=cache_hit,
            attempts=0 if cache_hit else 1,
        ),
    )


class FakeHttp:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def test_pure_pubchem_parsers_handle_current_api_shapes() -> None:
    properties = parse_pubchem_properties(PROPERTIES)
    assert properties["cid"] == 240
    assert properties["canonical_smiles"] == "C1=CC=C(C=C1)C=O"
    assert properties["isomeric_smiles"] == "C1=CC=C(C=C1)C=O"
    assert parse_pubchem_identifiers(IDENTIFIERS) == ["100-52-7"]
    assert parse_pubchem_synonyms(SYNONYMS) == ["Benzaldehyde", "100-52-7"]


def test_odor_parser_preserves_contributor_urls_and_licenses() -> None:
    odor = parse_pubchem_odor(ODOR)

    assert odor["odor"] == ["Characteristic almond odor", "Odor of bitter almond"]
    assert odor["odor_sources"] == ["Hazardous Substances Data Bank (HSDB)"]
    assert odor["odor_source_urls"] == ["https://pubchem.ncbi.nlm.nih.gov/source/hsdb/388"]
    assert odor["odor_license_urls"] == ["https://www.nlm.nih.gov/web_policies.html"]
    assert odor["odor_annotations"][0] == {
        "text": "Characteristic almond odor",
        "reference_number": "126",
        "source_name": "Hazardous Substances Data Bank (HSDB)",
        "source_url": "https://pubchem.ncbi.nlm.nih.gov/source/hsdb/388",
        "license_url": "https://www.nlm.nih.gov/web_policies.html",
    }


def test_lookup_combines_properties_identifiers_synonyms_and_odor() -> None:
    fake_http = FakeHttp(
        response(PROPERTIES, url="https://pubchem.ncbi.nlm.nih.gov/rest/pug/properties"),
        response(IDENTIFIERS),
        response(SYNONYMS),
        response(ODOR, url="https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/odor"),
    )
    client = PubChemClient(http_client=fake_http)

    result = client.lookup("benzaldehyde")

    assert result.status == "ok"
    assert result.values["query"] == "benzaldehyde"
    assert result.values["cid"] == 240
    assert result.values["cas_numbers"] == ["100-52-7"]
    assert result.values["synonyms"] == ["Benzaldehyde", "100-52-7"]
    assert result.values["odor"] == ["Characteristic almond odor", "Odor of bitter almond"]
    assert result.values["odor_sources"] == ["Hazardous Substances Data Bank (HSDB)"]
    assert result.cache_hit is True
    assert result.source_url.endswith("/properties")
    assert len(fake_http.calls) == 4
    assert fake_http.calls[1]["params"] == {"identifier_type": "CAS"}
    assert fake_http.calls[3]["params"] == {"heading": "Odor"}


def test_lookup_accepts_cas_and_can_skip_pug_view() -> None:
    fake_http = FakeHttp(response(PROPERTIES), response(IDENTIFIERS), response(SYNONYMS))
    client = PubChemClient(http_client=fake_http)

    result = client.lookup("100527", include_odor=False)

    assert result.status == "ok"
    assert result.values["cas_numbers"] == ["100-52-7"]
    assert result.values["odor"] == []
    assert len(fake_http.calls) == 3
    assert "/compound/name/100527/property/" in fake_http.calls[0]["url"]


def test_missing_odor_is_not_a_primary_lookup_failure() -> None:
    fake_http = FakeHttp(
        response(PROPERTIES),
        response(IDENTIFIERS),
        response(SYNONYMS),
        response({"Fault": {"Message": "No data"}}, status=404),
    )
    client = PubChemClient(http_client=fake_http)

    result = client.lookup("benzaldehyde")

    assert result.status == "ok"
    assert result.values["odor"] == []
    assert result.message == ""


def test_primary_not_found_and_malformed_payloads_are_explicit() -> None:
    fake_http = FakeHttp(
        response({"Fault": {}}, status=404),
        response({"PropertyTable": {"Properties": []}}),
    )
    client = PubChemClient(http_client=fake_http)

    missing = client.lookup("not-real")
    malformed = client.lookup("also-not-real")

    assert missing.status == "not_found"
    assert malformed.status == "parse_error"
    assert len(fake_http.calls) == 2


def test_pubchem_default_rate_is_below_five_requests_per_second(tmp_path: Any) -> None:
    client = PubChemClient(cache_dir=tmp_path)
    assert client.http.min_interval > 0.2
