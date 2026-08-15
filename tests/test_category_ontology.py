from trzip.category_ontology import CATEGORY_ONTOLOGY, category_ontology
from trzip.intelligence import _category, _broad_category


def test_every_public_detail_category_has_non_scoring_ontology_slots():
    assert len(CATEGORY_ONTOLOGY) == 16
    for category, definition in CATEGORY_ONTOLOGY.items():
        result = category_ontology(category)
        assert result["category"] == category
        assert result["entity_slots"]
        assert result["trigger_types"]
        assert 3 <= len(result["recommended_company_roles"]) <= 4
        assert result["affects_score"] is False


def test_hobby_beauty_and_event_contexts_are_classified_by_general_rules():
    assert _category("뜨개질 붐") == "lifestyle_behavior"
    assert _category("스킨케어 신제품") == "fashion_collectible"
    assert _category("서울국제도서전") == "place_experience"
    assert _broad_category(_category("뜨개질 붐")) == "lifestyle"
