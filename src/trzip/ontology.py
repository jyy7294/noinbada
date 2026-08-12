"""Evidence-first ontology primitives for TRZIP.

The ontology is deliberately separate from trend ranking.  Historical cases can
seed aliases and evidence paths, but they never add observations or ranking
points.  A company result is publishable only when at least ``min_companies``
unique companies are reachable through fully evidenced, publishable paths.
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata
from typing import Any, Iterable, Mapping


ALLOWED_NODE_TYPES = frozenset(
    {
        "trend",
        "term",
        "entity",
        "product_service",
        "person_place",
        "industry",
        "company",
        "stock",
        "evidence",
    }
)

DEFAULT_PUBLISHABLE_REVIEW_STATUSES = frozenset(
    {"verified", "approved", "published", "historical_reference"}
)

COMPANY_LINK_RELATIONS = frozenset(
    {
        "historical_business_link",
        "operates_in_industry",
        "documented_business_relationship",
        "listed_as",
    }
)

MINIMUM_PUBLISHED_COMPANIES = 5


class OntologyValidationError(ValueError):
    """Raised when a graph violates the evidence or schema contract."""


def normalize_label(value: str) -> str:
    """Return a deterministic label key without inventing a representative term."""

    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.casefold().split())


@dataclass(frozen=True)
class OntologyPath:
    """A forward evidence path through the graph."""

    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "evidence_ids": list(self.evidence_ids),
        }


class OntologyGraph:
    """Validated, deterministic, read-only view over an ontology JSON payload."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = deepcopy(dict(payload))
        self.schema_version = str(self._payload.get("schema_version", ""))
        self.metadata = deepcopy(dict(self._payload.get("metadata") or {}))
        self.nodes = tuple(deepcopy(list(self._payload.get("nodes") or [])))
        self.edges = tuple(deepcopy(list(self._payload.get("edges") or [])))
        self.evidence = tuple(deepcopy(list(self._payload.get("evidence") or [])))

        self._node_by_id = self._unique_map(self.nodes, "node")
        self._edge_by_id = self._unique_map(self.edges, "edge")
        self._evidence_by_id = self._unique_map(self.evidence, "evidence")
        self._outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.edges:
            self._outgoing[str(edge.get("from_node"))].append(edge)
        for edges in self._outgoing.values():
            edges.sort(key=lambda item: str(item.get("id", "")))

        self._term_by_key: dict[str, str] = {}
        for node in self.nodes:
            if node.get("type") != "term":
                continue
            key = str(node.get("normalized_label") or normalize_label(node.get("label", "")))
            self._term_by_key.setdefault(key, str(node["id"]))

        self._validate()

    @staticmethod
    def _unique_map(items: Iterable[Mapping[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            item_id = str(item.get("id", "")).strip()
            if not item_id:
                raise OntologyValidationError(f"{kind} id is required")
            if item_id in result:
                raise OntologyValidationError(f"duplicate {kind} id: {item_id}")
            result[item_id] = dict(item)
        return result

    @classmethod
    def load(cls, path: str | Path) -> "OntologyGraph":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def to_payload(self) -> dict[str, Any]:
        return deepcopy(self._payload)

    def node(self, node_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self._node_by_id[node_id])
        except KeyError as exc:
            raise KeyError(f"unknown ontology node: {node_id}") from exc

    def evidence_record(self, evidence_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self._evidence_by_id[evidence_id])
        except KeyError as exc:
            raise KeyError(f"unknown ontology evidence: {evidence_id}") from exc

    def term_node_id(self, label: str) -> str | None:
        return self._term_by_key.get(normalize_label(label))

    def _validate(self) -> None:
        evidence_node_ids = {
            str(node["id"])
            for node in self.nodes
            if node.get("type") == "evidence"
        }
        for node in self.nodes:
            node_type = str(node.get("type", ""))
            if node_type not in ALLOWED_NODE_TYPES:
                raise OntologyValidationError(
                    f"unsupported node type {node_type!r} for {node['id']}"
                )
            if not str(node.get("label", "")).strip():
                raise OntologyValidationError(f"node label is required: {node['id']}")

        for record in self.evidence:
            evidence_id = str(record["id"])
            if evidence_id not in evidence_node_ids:
                raise OntologyValidationError(
                    f"evidence record has no evidence node: {evidence_id}"
                )
            if not str(record.get("url", "")).strip():
                raise OntologyValidationError(f"evidence URL is required: {evidence_id}")
            if not str(record.get("review_status", "")).strip():
                raise OntologyValidationError(
                    f"evidence review_status is required: {evidence_id}"
                )
            if not dict(record.get("provenance") or {}):
                raise OntologyValidationError(
                    f"evidence provenance is required: {evidence_id}"
                )

        for edge in self.edges:
            edge_id = str(edge["id"])
            start = str(edge.get("from_node", ""))
            end = str(edge.get("to_node", ""))
            if start not in self._node_by_id or end not in self._node_by_id:
                raise OntologyValidationError(f"edge endpoint is missing: {edge_id}")
            if not str(edge.get("relation_type", "")).strip():
                raise OntologyValidationError(f"edge relation_type is required: {edge_id}")
            if not str(edge.get("review_status", "")).strip():
                raise OntologyValidationError(f"edge review_status is required: {edge_id}")
            if not dict(edge.get("provenance") or {}):
                raise OntologyValidationError(f"edge provenance is required: {edge_id}")

            evidence_ids = tuple(str(value) for value in edge.get("evidence_ids") or [])
            if not evidence_ids:
                raise OntologyValidationError(f"edge has no evidence: {edge_id}")
            missing = [value for value in evidence_ids if value not in self._evidence_by_id]
            if missing:
                raise OntologyValidationError(
                    f"edge references missing evidence {missing}: {edge_id}"
                )

            start_type = str(self._node_by_id[start]["type"])
            end_type = str(self._node_by_id[end]["type"])
            touches_company = "company" in {start_type, end_type}
            touches_stock = "stock" in {start_type, end_type}
            if (touches_company or touches_stock) and not all(
                str(self._evidence_by_id[value].get("url", "")).strip()
                for value in evidence_ids
            ):
                raise OntologyValidationError(
                    f"company or stock edge lacks URL evidence: {edge_id}"
                )

    def trace_paths(
        self,
        start_node_id: str,
        *,
        target_types: Iterable[str] = ("company",),
        max_hops: int = 5,
        allowed_review_statuses: Iterable[str] | None = None,
    ) -> list[OntologyPath]:
        """Trace deterministic forward paths whose every edge is evidenced."""

        if start_node_id not in self._node_by_id:
            raise KeyError(f"unknown ontology node: {start_node_id}")
        if max_hops < 1:
            return []

        targets = frozenset(target_types)
        allowed = (
            None
            if allowed_review_statuses is None
            else frozenset(str(value) for value in allowed_review_statuses)
        )
        queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = deque(
            [(start_node_id, (start_node_id,), (), ())]
        )
        paths: list[OntologyPath] = []

        while queue:
            node_id, node_ids, edge_ids, evidence_ids = queue.popleft()
            if len(edge_ids) >= max_hops:
                continue
            for edge in self._outgoing.get(node_id, ()):  # sorted in __init__
                if allowed is not None and str(edge["review_status"]) not in allowed:
                    continue
                next_id = str(edge["to_node"])
                if next_id in node_ids:
                    continue
                next_nodes = (*node_ids, next_id)
                next_edges = (*edge_ids, str(edge["id"]))
                next_evidence = tuple(
                    sorted({*evidence_ids, *(str(v) for v in edge["evidence_ids"])})
                )
                next_path = OntologyPath(next_nodes, next_edges, next_evidence)
                if str(self._node_by_id[next_id]["type"]) in targets:
                    paths.append(next_path)
                queue.append((next_id, next_nodes, next_edges, next_evidence))

        paths.sort(key=lambda path: (len(path.edge_ids), path.node_ids, path.edge_ids))
        return paths

    def resolve_companies(
        self,
        start_node_id: str,
        *,
        min_companies: int = MINIMUM_PUBLISHED_COMPANIES,
        max_hops: int = 5,
        publishable_review_statuses: Iterable[str] = DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
    ) -> dict[str, Any]:
        """Return evidence paths and enforce the no-padding company-count gate."""

        if min_companies < 1:
            raise ValueError("min_companies must be at least one")
        paths = self.trace_paths(
            start_node_id,
            target_types=("company",),
            max_hops=max_hops,
            allowed_review_statuses=publishable_review_statuses,
        )
        first_path_by_company: dict[str, OntologyPath] = {}
        for path in paths:
            company_id = path.node_ids[-1]
            first_path_by_company.setdefault(company_id, path)

        companies: list[dict[str, Any]] = []
        for company_id in sorted(first_path_by_company):
            path = first_path_by_company[company_id]
            companies.append(
                {
                    "company": self.node(company_id),
                    "path": path.as_dict(),
                    "edges": [deepcopy(self._edge_by_id[value]) for value in path.edge_ids],
                    "evidence": [
                        self.evidence_record(value) for value in path.evidence_ids
                    ],
                }
            )

        publishable = len(companies) >= min_companies
        return {
            "status": "published" if publishable else "ontology_incomplete",
            "publishable": publishable,
            "minimum_required": min_companies,
            "company_count": len(companies),
            "companies": companies,
            "reason": (
                "minimum evidence-backed company count met"
                if publishable
                else "fewer than the required evidence-backed companies; no filler added"
            ),
        }

    def resolve_term(
        self,
        label: str,
        *,
        min_companies: int = MINIMUM_PUBLISHED_COMPANIES,
        max_hops: int = 5,
    ) -> dict[str, Any]:
        node_id = self.term_node_id(label)
        if node_id is None:
            return {
                "status": "ontology_incomplete",
                "publishable": False,
                "minimum_required": min_companies,
                "company_count": 0,
                "companies": [],
                "reason": "representative term is not present in the reviewed ontology",
            }
        result = self.resolve_companies(
            node_id,
            min_companies=min_companies,
            max_hops=max_hops,
        )
        result["term_node_id"] = node_id
        return result
