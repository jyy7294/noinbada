from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from trzip.ontology import (
    MINIMUM_PUBLISHED_COMPANIES,
    OntologyGraph,
    OntologyValidationError,
)


ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "data" / "ontology_seed.json"
ENRICHMENT_PATH = ROOT / "data" / "ontology_enrichment.json"
SOURCE_JSON = (
    ROOT.parents[1] / "work" / "spreadsheet-audit" / "ontology-source.json"
)


def _load_builder_module():
    module_path = ROOT / "scripts" / "build_ontology_seed.py"
    spec = importlib.util.spec_from_file_location("build_ontology_seed", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_graph(company_count: int) -> OntologyGraph:
    nodes = [
        {"id": "term:t", "type": "term", "label": "테스트", "metadata": {}},
    ]
    edges = []
    evidence = []
    for index in range(company_count):
        evidence_id = f"evidence:e{index}"
        company_id = f"company:c{index}"
        nodes.extend(
            [
                {
                    "id": company_id,
                    "type": "company",
                    "label": f"기업 {index}",
                    "metadata": {},
                },
                {
                    "id": evidence_id,
                    "type": "evidence",
                    "label": f"근거 {index}",
                    "metadata": {},
                },
            ]
        )
        evidence.append(
            {
                "id": evidence_id,
                "url": f"https://example.com/{index}",
                "title": f"근거 {index}",
                "review_status": "approved",
                "provenance": {"source": "test", "row": index + 1},
            }
        )
        edges.append(
            {
                "id": f"edge:e{index}",
                "from_node": "term:t",
                "to_node": company_id,
                "relation_type": "historical_business_link",
                "evidence_ids": [evidence_id],
                "review_status": "approved",
                "provenance": {"source": "test", "row": index + 1},
            }
        )
    return OntologyGraph(
        {
            "schema_version": "test-v1",
            "nodes": nodes,
            "edges": edges,
            "evidence": evidence,
        }
    )


def test_checked_in_seed_is_valid_and_not_a_ranking_input():
    graph = OntologyGraph.load(SEED_PATH)

    assert graph.metadata["usage"]["historical_seed"] is True
    assert graph.metadata["usage"]["ranking_input"] is False
    assert graph.metadata["usage"]["current_trend_claim"] is False
    assert graph.metadata["publication_gate"][
        "minimum_unique_evidence_backed_companies"
    ] == MINIMUM_PUBLISHED_COMPANIES
    assert graph.metadata["publication_gate"]["padding_forbidden"] is True
    assert graph.metadata["build_stats"]["historical_trend_rows"] == 298
    assert graph.metadata["build_stats"]["industry_structure_rows"] == 282


def test_seed_generation_is_deterministic_when_extracted_values_are_available():
    if not SOURCE_JSON.exists():
        pytest.skip("offline extracted workbook values are not in this checkout")
    module = _load_builder_module()

    first = module.build_seed_from_file(SOURCE_JSON)
    second = module.build_seed_from_file(SOURCE_JSON)

    assert module.canonical_json(first) == module.canonical_json(second)
    assert module.canonical_json(first) == SEED_PATH.read_text(encoding="utf-8")


def test_every_edge_has_provenance_and_resolved_url_evidence():
    graph = OntologyGraph.load(SEED_PATH)
    evidence_ids = {record["id"] for record in graph.evidence}

    for edge in graph.edges:
        assert edge["provenance"]
        assert edge["evidence_ids"]
        assert set(edge["evidence_ids"]) <= evidence_ids
        for evidence_id in edge["evidence_ids"]:
            record = graph.evidence_record(evidence_id)
            assert record["url"].startswith(("http://", "https://"))
            assert record["provenance"]


def test_industry_structure_is_not_misrepresented_as_company_transaction():
    graph = OntologyGraph.load(SEED_PATH)
    industry_edges = [
        edge
        for edge in graph.edges
        if edge["relation_type"] == "industry_structure_supply"
    ]

    assert len(industry_edges) == 282
    assert all(edge["metadata"]["structure_only"] is True for edge in industry_edges)
    assert all(edge["metadata"]["company_transaction"] is False for edge in industry_edges)
    assert all(
        graph.node(edge["from_node"])["type"] == "industry"
        and graph.node(edge["to_node"])["type"] == "industry"
        for edge in industry_edges
    )


def test_explicit_company_relationships_only_and_ambiguous_party_is_skipped():
    graph = OntologyGraph.load(SEED_PATH)
    relationships = [
        edge
        for edge in graph.edges
        if edge["relation_type"] == "documented_business_relationship"
    ]

    assert len(relationships) == 8
    assert graph.metadata["build_stats"]["company_relationship_rows_unparsed"] == 1
    assert all(
        graph.node(edge["from_node"])["type"] == "company"
        and graph.node(edge["to_node"])["type"] == "company"
        for edge in relationships
    )
    assert not any("파트너" in graph.node(edge["to_node"])["label"] for edge in relationships)


def test_edge_without_evidence_is_rejected():
    graph = _tiny_graph(1)
    payload = graph.to_payload()
    payload["edges"][0]["evidence_ids"] = []

    with pytest.raises(OntologyValidationError, match="no evidence"):
        OntologyGraph(payload)


def test_five_company_publication_gate_never_pads_results():
    four = _tiny_graph(MINIMUM_PUBLISHED_COMPANIES - 1).resolve_companies("term:t")
    five = _tiny_graph(MINIMUM_PUBLISHED_COMPANIES).resolve_companies("term:t")

    assert four["status"] == "ontology_incomplete"
    assert four["publishable"] is False
    assert four["company_count"] == MINIMUM_PUBLISHED_COMPANIES - 1
    assert len(four["companies"]) == MINIMUM_PUBLISHED_COMPANIES - 1
    assert "no filler" in four["reason"]
    assert five["status"] == "published"
    assert five["publishable"] is True
    assert five["company_count"] == MINIMUM_PUBLISHED_COMPANIES


def test_seed_path_trace_preserves_every_edge_and_evidence_record():
    graph = OntologyGraph.load(SEED_PATH)
    node_id = graph.term_node_id("두바이 쫀득쿠키")
    assert node_id is not None

    paths = graph.trace_paths(
        node_id,
        target_types=("company",),
        allowed_review_statuses=("historical_reference",),
    )

    assert len({path.node_ids[-1] for path in paths}) == 3
    for path in paths:
        assert path.node_ids[0] == node_id
        assert graph.node(path.node_ids[-1])["type"] == "company"
        assert path.edge_ids
        assert path.evidence_ids
        assert all(graph.evidence_record(value)["url"] for value in path.evidence_ids)


def test_real_seed_with_three_companies_fails_new_five_company_gate():
    graph = OntologyGraph.load(SEED_PATH)

    result = graph.resolve_term("두바이 쫀득쿠키")

    assert result["company_count"] == 3
    assert result["minimum_required"] == 5
    assert result["status"] == "ontology_incomplete"
    assert result["publishable"] is False


def test_reviewed_enrichment_preserves_seed_and_publishes_malbok_without_padding():
    seed_before = SEED_PATH.read_bytes()
    graph = OntologyGraph.load_merged(SEED_PATH, ENRICHMENT_PATH)

    result = graph.resolve_term("말복")

    assert SEED_PATH.read_bytes() == seed_before
    assert result["status"] == "published"
    assert result["company_count"] == 6
    assert {
        company["company"]["metadata"]["ticker"]
        for company in result["companies"]
    } == {"001680", "003680", "027740", "031440", "136480", "139480"}
    assert all(
        record["url"].startswith("https://")
        for company in result["companies"]
        for record in company["evidence"]
    )
    assert all(
        edge["review_status"] == "approved"
        for company in result["companies"]
        for edge in company["edges"]
    )


def test_reviewed_iam_solo_aliases_publish_exactly_five_officially_evidenced_companies():
    graph = OntologyGraph.load_merged(SEED_PATH, ENRICHMENT_PATH)
    expected_tickers = {"030200", "034120", "035760", "053210", "402340"}

    for observed_term in ("나는 SOLO", "나는솔로", "나는 솔로", "나솔"):
        result = graph.resolve_term(observed_term)

        assert result["status"] == "published"
        assert result["company_count"] == 5
        assert {
            company["company"]["metadata"]["ticker"]
            for company in result["companies"]
        } == expected_tickers
        assert all(
            record["review_status"] == "approved" and record["url"].startswith("https://")
            for company in result["companies"]
            for record in company["evidence"]
        )
        assert all(
            "/dst/irReference/" not in record["url"]
            for company in result["companies"]
            for record in company["evidence"]
        )


def test_reviewed_aliases_return_only_same_node_publishable_evidence():
    graph = OntologyGraph.load_merged(SEED_PATH, ENRICHMENT_PATH)

    aliases = graph.reviewed_aliases("나솔")

    assert {item["label"] for item in aliases} == {"나는솔로", "나는 솔로", "나솔"}
    assert {item["target_node_label"] for item in aliases} == {"나는 SOLO"}
    assert all(
        record["url"].startswith("https://")
        for item in aliases
        for record in item["evidence"]
    )
def test_iam_solo_business_edges_are_three_core_and_two_value_chain():
    graph = OntologyGraph.load_merged(SEED_PATH, ENRICHMENT_PATH)
    relation_edges = [
        edge
        for edge in graph.edges
        if edge["from_node"] == "term:reviewed:iam-solo"
    ]

    assert len(relation_edges) == 5
    assert sum(edge["metadata"]["relation_tier"] == "core" for edge in relation_edges) == 3
    assert sum(
        edge["metadata"]["relation_tier"] == "value_chain"
        for edge in relation_edges
    ) == 2
    assert all(edge["relation_type"] != "listed_as" for edge in relation_edges)
    assert all(edge["metadata"]["not_a_buy_signal"] is True for edge in relation_edges)


def test_iam_solo_ena_path_separates_program_schedule_from_channel_ownership():
    graph = OntologyGraph.load_merged(SEED_PATH, ENRICHMENT_PATH)
    relation_edges = {
        edge["to_node"]: edge
        for edge in graph.edges
        if edge["from_node"] == "term:reviewed:iam-solo"
    }

    ktsky_edge = relation_edges["company:kr:kospi:053210"]
    kt_edge = relation_edges["company:kr:kospi:030200"]
    assert ktsky_edge["evidence_ids"] == [
        "evidence:reviewed:sbsplus-iam-solo",
        "evidence:reviewed:ktsky-iam-solo",
    ]
    assert kt_edge["evidence_ids"] == [
        "evidence:reviewed:sbsplus-iam-solo",
        "evidence:reviewed:ktsky-iam-solo",
        "evidence:reviewed:krx-ktsky-053210",
    ]

    channel_evidence = next(
        record
        for record in graph.evidence
        if record["id"] == "evidence:reviewed:ktsky-iam-solo"
    )
    assert channel_evidence["evidence_type"] == "official_filing_broadcast_channel_operation"
    assert "나는 SOLO 편성 사실은 SBS Plus 공식 편성 페이지로 별도 확인" in channel_evidence["summary"]


def test_alias_lookup_is_evidenced_and_never_changes_the_matched_input_label():
    graph = OntologyGraph.load_merged(SEED_PATH, ENRICHMENT_PATH)

    match = graph.lookup("  삼성전자  ")
    resolution = graph.resolve_term("삼성전자")

    assert match is not None
    assert match["matched_label"] == "삼성전자"
    assert match["target_node_label"] == "005930"
    assert match["match_type"] == "reviewed_company_identifier_alias"
    assert match["review_status"] == "approved"
    assert all(record["url"].startswith("https://") for record in match["evidence"])
    assert resolution["company_count"] == 1
    assert resolution["publishable"] is False


def test_unreviewed_alias_is_validated_but_not_used_for_lookup():
    payload = _tiny_graph(1).to_payload()
    payload["aliases"] = [
        {
            "id": "alias:pending",
            "label": "미검수 별칭",
            "target_node_id": "term:t",
            "evidence_ids": ["evidence:e0"],
            "review_status": "review_required",
            "provenance": {"source": "test"},
        }
    ]
    graph = OntologyGraph(payload)

    assert graph.lookup("미검수 별칭") is None


def test_alias_without_url_evidence_is_rejected():
    payload = _tiny_graph(1).to_payload()
    payload["evidence"][0]["url"] = ""
    payload["aliases"] = [
        {
            "id": "alias:bad",
            "label": "위험한 별칭",
            "target_node_id": "term:t",
            "evidence_ids": ["evidence:e0"],
            "review_status": "approved",
            "provenance": {"source": "test"},
        }
    ]

    with pytest.raises(OntologyValidationError, match="evidence URL is required"):
        OntologyGraph(payload)


def test_publishable_alias_cannot_use_unreviewed_evidence():
    payload = _tiny_graph(1).to_payload()
    payload["nodes"].append(
        {
            "id": "evidence:alias-pending",
            "type": "evidence",
            "label": "미검수 별칭 근거",
            "metadata": {},
        }
    )
    payload["evidence"].append(
        {
            "id": "evidence:alias-pending",
            "url": "https://example.com/pending-alias",
            "title": "미검수 별칭 근거",
            "review_status": "review_required",
            "provenance": {"source": "test"},
        }
    )
    payload["aliases"] = [
        {
            "id": "alias:bad-review",
            "label": "검수되지 않은 근거의 별칭",
            "target_node_id": "term:t",
            "evidence_ids": ["evidence:alias-pending"],
            "review_status": "approved",
            "provenance": {"source": "test"},
        }
    ]

    with pytest.raises(
        OntologyValidationError,
        match="publishable alias references unreviewed evidence",
    ):
        OntologyGraph(payload)


def test_publishable_company_edge_cannot_use_unreviewed_evidence():
    payload = _tiny_graph(1).to_payload()
    payload["evidence"][0]["review_status"] = "review_required"

    with pytest.raises(
        OntologyValidationError,
        match="publishable edge references unreviewed evidence",
    ):
        OntologyGraph(payload)


def test_missing_enrichment_overlay_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError, match="enrichment overlay is missing"):
        OntologyGraph.load_merged(SEED_PATH, tmp_path / "missing.json")
