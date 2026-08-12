from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


# 수동 정답셋: 이름을 "흥미로운 문장"으로 바꾸는 목록이 아니라
# 동음이의어의 정체와 안전한 카테고리를 고정하는 회귀 테스트 자료다.
GROUND_TRUTH = {
    "피의 게임": ("피의 게임", "screen_content", "서바이벌 예능 '피의 게임' 관련 관심 증가", ("서바이벌 예능", "피의 게임 출연진", "피의 게임 시즌")),
    "블루레이": ("블루레이", "product_brand", "블루레이 영상매체·한정판 관련 관심 증가", ("블루레이 한정판", "블루레이 플레이어", "4K 블루레이")),
    "데이즈드": ("데이즈드", "screen_content", "패션·문화 매거진 데이즈드 관련 관심 증가", ("데이즈드 코리아", "데이즈드 화보", "패션 매거진")),
    "관리 종목": ("관리종목", "investment_market", "증시 관리종목 지정·해제 관련 검색 증가", ("관리종목 지정", "관리종목 해제", "거래정지")),
    "네이마르": ("네이마르", "sports_participation", "축구선수 네이마르 관련 관심 증가", ("네이마르 경기", "네이마르 이적", "네이마르 부상")),
    "말복": ("말복", "seasonal_food_ritual", "말복을 앞두고 삼계탕·보양식 관련 관심 증가", ("삼계탕", "보양식", "복날 음식")),
    "두쫀쿠": ("두쫀쿠", "food_culinary", "두바이 초콜릿 계열 디저트 '두쫀쿠' 관련 관심 증가", ("두바이 초콜릿", "디저트", "두쫀쿠 만들기")),
    "두바이 초콜릿": ("두바이 초콜릿", "food_culinary", "두바이 초콜릿 제품·레시피 관련 관심 증가", ("카다이프", "피스타치오", "초콜릿 만들기")),
    "불닭": ("불닭", "food_culinary", "불닭 브랜드·매운 라면 관련 관심 증가", ("불닭볶음면", "불닭 소스", "매운 라면")),
    "오징어 게임": ("오징어 게임", "screen_content", "넷플릭스 시리즈 '오징어 게임' 관련 관심 증가", ("넷플릭스", "오징어 게임 출연진", "오징어 게임 시즌")),
    "리센느": ("리센느", "music_performance", "K-pop 그룹 리센느 관련 관심 증가", ("리센느 신곡", "리센느 무대", "리센느 멤버")),
    "야구 직관": ("야구 직관", "sports_attendance", "프로야구 현장 관람·응원 문화 관련 관심 증가", ("프로야구 예매", "야구장 먹거리", "응원가")),
    "러닝크루": ("러닝크루", "sports_participation", "도심 러닝 모임·러닝크루 참여 관심 증가", ("러닝화", "러닝 모임", "마라톤")),
    "포켓몬": ("포켓몬", "gaming_digital", "포켓몬 게임·상품·IP 관련 관심 증가", ("포켓몬 게임", "포켓몬 카드", "포켓몬 굿즈")),
    "삼성전자": ("삼성전자", "investment_market", "삼성전자 종목·기업 관련 검색 증가", ("삼성전자 주가", "반도체", "실적")),
    "에코프로비엠": ("에코프로비엠", "investment_market", "에코프로비엠 종목·2차전지 관련 검색 증가", ("에코프로비엠 주가", "2차전지", "양극재")),
    "수건": ("수건", "lifestyle_behavior", "수건 관련 생활정보 검색 증가—구체 맥락은 추가 확인 필요", ("수건 세탁", "호텔 수건", "수건 관리")),
    "러닝화": ("러닝화", "fashion_collectible", "러닝화 제품·착화·구매 관련 관심 증가", ("러닝화 추천", "러닝화 브랜드", "러닝화 사이즈")),
    "한강 수영장": ("한강 수영장", "place_experience", "한강 수영장 이용·예약 관련 관심 증가", ("한강 수영장 예약", "운영시간", "입장료")),
    "캐릭터 키링": ("캐릭터 키링", "fashion_collectible", "캐릭터 키링·가방 꾸미기 관련 관심 증가", ("키링", "가방 꾸미기", "캐릭터 굿즈")),
    "로우매치 인트": ("리그 오브 레전드 패치", "gaming_digital", "리그 오브 레전드 패치 관련 관심 증가", ("LoL 패치", "챔피언 패치", "게임 업데이트")),
    "NCT 시온": ("NCT WISH 시온", "music_performance", "NCT WISH 멤버 시온 관련 관심 증가", ("NCT WISH", "시온", "K-pop")),
    "JIN LIGHTS UP CHARM CITY": ("BTS 진 볼티모어 공연", "music_performance", "BTS 진의 볼티모어 공연 관련 관심 증가", ("BTS 진", "볼티모어", "진 콘서트")),
    "#JIN_IN_BALTIMORE_D2": ("BTS 진 볼티모어 공연", "music_performance", "BTS 진의 볼티모어 공연 해시태그 확산", ("BTS 진", "볼티모어", "진 콘서트")),
    "김지수": ("김지수", "unclassified", "동명이인 가능성이 있어 인물·사건 맥락 확인 필요", ()),
    "차상현": ("차상현", "unclassified", "인물명 검색 증가—소속·사건 맥락 확인 필요", ()),
    "스네즈나": ("스네즈나", "unclassified", "고유명사 관련 관심 증가—대상 식별 필요", ()),
    "챱챱 물개": ("챱챱 물개", "participation_meme", "'챱챱 물개' 표현·밈 관련 관심 증가", ("물개 밈", "챱챱", "밈")),
    "보답한대요": ("보답한대요", "unclassified", "문장형 표현 확산—원문 맥락 확인 필요", ()),
    "국가장학금": ("국가장학금", "policy_issue", "국가장학금 신청·지급 관련 검색 증가", ("국가장학금 신청", "소득구간", "지급일")),
    "불꽃축제": ("불꽃축제", "place_experience", "불꽃축제 관람·일정·장소 관련 관심 증가", ("불꽃축제 일정", "불꽃축제 명당", "불꽃축제 교통")),
    "005930": ("삼성전자", "investment_market", "삼성전자 종목코드 005930 관련 검색 증가", ("삼성전자 주가", "반도체", "실적")),
}

ALIASES = {
    "관리종목": "관리 종목", "두바이초콜릿": "두바이 초콜릿",
    "오징어게임": "오징어 게임", "러닝 크루": "러닝크루",
    "nct 시온": "NCT 시온", "에코프로BM": "에코프로비엠",
}

PERSON_NAME_RE = re.compile(r"^[가-힣]{2,4}$")
COMMON_KOREAN_SURNAMES = frozenset("김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용")
REVIEW_STATUSES = frozenset({"approved", "rejected", "needs_revision"})


def normalize_event_key(raw: str) -> str:
    """Normalize presentation variants without inventing semantic aliases."""
    value = unicodedata.normalize("NFKC", str(raw or "")).strip()
    value = re.sub(r"^[#＃]+", "", value)
    value = value.replace("_", " ")
    value = re.sub(r"[·ㆍ:：/\\|]+", " ", value)
    return " ".join(value.split()).casefold()


def _lookup_key(raw: str) -> str:
    normalized = normalize_event_key(raw)
    alias_lookup = {normalize_event_key(key): value for key, value in ALIASES.items()}
    aliased = alias_lookup.get(normalized)
    if aliased:
        return aliased

    exact_lookup = {normalize_event_key(key): key for key in GROUND_TRUTH}
    if normalized in exact_lookup:
        return exact_lookup[normalized]

    spaceless = normalized.replace(" ", "")
    matches = [key for key in GROUND_TRUTH if normalize_event_key(key).replace(" ", "") == spaceless]
    return matches[0] if len(matches) == 1 else " ".join(str(raw or "").strip().split())


def resolve_event(raw: str, sources: set[str]) -> dict:
    compact = " ".join(unicodedata.normalize("NFKC", str(raw or "")).strip().split())
    key = _lookup_key(compact)
    truth = GROUND_TRUTH.get(key)
    if truth:
        display, category, _reference_context, keyword_candidates = truth
        context_status = "needs_context" if category == "unclassified" else "resolved_reference"
    else:
        display, category, keyword_candidates = compact, None, ()
        looks_like_person = (
            bool(PERSON_NAME_RE.fullmatch(compact))
            and len(compact) == 3
            and compact[0] in COMMON_KOREAN_SURNAMES
        )
        context_status = "ambiguous_person" if looks_like_person else "needs_context"
    # Resolution may classify an entity, but it must never invent a public
    # event title or causal narrative. The public summary stays anchored to the
    # exact observed expression; contextual research is a separate workflow.
    summary = observation_summary(compact, sources)
    return {
        "canonical": display,
        "category": category,
        "phenomenon_summary": summary,
        "context_status": context_status,
        "keyword_candidates": list(keyword_candidates),
        "ground_truth_match": bool(truth),
    }


def observation_summary(raw: str, sources: set[str]) -> str:
    compact = " ".join(unicodedata.normalize("NFKC", str(raw or "")).strip().split())
    term = compact or "표현 미확인"
    return f'"{term}" · {source_observation_label(sources)}'


def source_observation_label(sources: set[str]) -> str:
    if sources == {"x", "google_trends"}:
        return "X 한국 실시간·Google Trends KR에서 함께 관측"
    if sources == {"x"}:
        return "X 한국 실시간에서 관측"
    if sources == {"google_trends"}:
        return "Google Trends KR에서 관측"
    labels = {"x": "X 한국 실시간", "google_trends": "Google Trends KR"}
    named = [labels.get(source, source) for source in sorted(sources)]
    return ("·".join(named) + "에서 관측") if named else "관측 출처 확인 필요"


def load_company_review_overrides(path: Path | None = None) -> dict[str, str]:
    path = path or Path(__file__).resolve().parents[2] / "config" / "company_review_overrides.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("company review overrides must be a JSON object")
    invalid = {str(key): str(value) for key, value in data.items() if str(value) not in REVIEW_STATUSES}
    if invalid:
        raise ValueError(f"invalid company review status: {invalid}")
    return {str(key): str(value) for key, value in data.items()}


def company_evidence_status(company: dict) -> dict:
    """Classify evidence independently from value-chain and team-review labels."""
    strength = company.get("strength", "sector_watch")
    kind = str(company.get("evidence_kind") or "")
    url = str(company.get("evidence_url") or "")
    parsed = urlparse(url) if url else None
    valid_url = bool(parsed and parsed.scheme == "https" and parsed.netloc)
    official_kind = (
        kind.startswith("company_official_")
        or kind in {"official_content_page", "opendart_filing", "company_ir"}
    )
    pending_kind = "pending" in kind or kind in {
        "category_exposure_pending", "consumer_path_hypothesis", "sector_watch_only",
        "industry_structure_reference", "exclusion_rule",
    }
    if strength == "excluded":
        status = "excluded"
    elif strength == "sector_watch":
        status = "industry_structure_only"
    elif valid_url and official_kind and not pending_kind:
        status = "official_evidence"
    else:
        status = "pending_evidence"
    return {
        "verification_status": status,
        "evidence_url_valid": valid_url,
        "evidence_official": status == "official_evidence",
        "evidence_review_reason": (
            "공식 URL과 관계 유형이 확인됨" if status == "official_evidence"
            else "산업 구조 관찰 후보이며 개별 계약·제품 관계는 미확인" if status == "industry_structure_only"
            else "연결 제외" if status == "excluded"
            else "공식 관계 문서 또는 관계 유형 검증이 추가로 필요"
        ),
    }


def relation_display(company: dict, reviews: dict[str, str]) -> dict:
    tier = company.get("relation_tier", "adjacent")
    label = {"core": "직접 관계", "value_chain": "가치사슬", "adjacent": "산업 관찰", "excluded": "연결 제외"}.get(tier, "산업 관찰")
    key = f"{company.get('company','')}|{company.get('evidence_url') or ''}"
    review = reviews.get(key, "unreviewed")
    return {
        "relation_display_type": label,
        "team_review_status": review,
        "team_review_label": {"approved": "팀 검수 승인", "rejected": "팀 검수 제외", "needs_revision": "팀 재검토", "unreviewed": "팀 미검수"}.get(review, "팀 미검수"),
    }


def evaluate_resolution(rows: list[dict]) -> dict:
    evaluated = [row for row in rows if row.get("ground_truth_expected")]
    correct_name = sum(row.get("display_name") == row["ground_truth_expected"].get("display_name") for row in evaluated)
    correct_category = sum(row.get("category") == row["ground_truth_expected"].get("category") for row in evaluated)
    total = len(evaluated)
    return {
        "ground_truth_size": len(GROUND_TRUTH),
        "evaluated_count": total,
        "name_accuracy": round(correct_name / total, 4) if total else None,
        "category_accuracy": round(correct_category / total, 4) if total else None,
        "status": "measured" if total else "awaiting_ground_truth_overlap",
        "scope": "reference_overlap_regression_not_holdout",
        "warning": "규칙에 포함된 수동 정답셋과의 회귀 일치율이며, 미관측 신규어 일반화 정확도가 아닙니다.",
    }
