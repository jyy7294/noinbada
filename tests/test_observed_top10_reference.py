from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_verified_august_14_observed_top10_reference_is_stable() -> None:
    document = json.loads(
        (ROOT / "examples" / "observed-top10-2026-08-14.json").read_text(
            encoding="utf-8"
        )
    )
    top10 = document["top10"]
    assert document["artifact_role"] == "verified_reference_output_not_ranking_input"
    assert [item["rank"] for item in top10] == list(range(1, 11))
    assert [item["trend"] for item in top10] == [
        "개기일식",
        "페르세우스 유성우",
        "말복·삼계탕",
        "불꽃축제",
        "메츠 대 브레이브스",
        "맨유 vs 리즈",
        "오디세이 영화",
        "데포르티보 vs 레알 마드리드",
        "휴머노이드 로봇",
        "홈플러스 재개장",
    ]
    assert all(set(item["sources"]) <= {"x", "google_trends"} for item in top10)
    assert all(item["score"] >= 0 for item in top10)
