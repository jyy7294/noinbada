"""Category-specific ontology slots for trend context enrichment.

The definitions describe which entities and trigger signals should be sought
after X/Google observe a term.  They never create observations or ranking
points and therefore cannot act as a manual promotion whitelist.
"""

from __future__ import annotations

from copy import deepcopy


CATEGORY_ONTOLOGY_VERSION = "category-ontology-v1"

CATEGORY_ONTOLOGY = {
    "food_culinary": {
        "entity_slots": ["product", "brand", "ingredient", "recipe_or_format", "sales_channel"],
        "trigger_types": ["product_launch", "sellout", "sales_growth", "creator_spread", "seasonal_demand"],
        "company_roles": ["raw_materials_components", "manufacturing_development", "distribution", "retail_sales"],
    },
    "seasonal_food_ritual": {
        "entity_slots": ["occasion", "food", "brand", "ingredient", "sales_channel"],
        "trigger_types": ["calendar_event", "seasonal_demand", "sales_growth", "menu_launch"],
        "company_roles": ["raw_materials_components", "manufacturing_development", "distribution", "retail_sales"],
    },
    "music_performance": {
        "entity_slots": ["artist", "work", "performance", "label_or_agency", "venue_or_platform"],
        "trigger_types": ["release", "chart_growth", "ticket_sellout", "performance", "campaign"],
        "company_roles": ["content_production", "distribution", "platform_service", "event_sponsorship"],
    },
    "screen_content": {
        "entity_slots": ["work", "director", "cast", "production_company", "distributor_or_platform"],
        "trigger_types": ["release", "trailer_release", "ticket_sellout", "audience_growth", "casting_announcement", "festival_event"],
        "company_roles": ["content_production", "distribution", "platform_service", "brand_marketing"],
    },
    "gaming_digital": {
        "entity_slots": ["game", "developer", "publisher", "platform", "update_or_event"],
        "trigger_types": ["release", "major_update", "player_growth", "esports_event", "collaboration"],
        "company_roles": ["content_production", "distribution", "platform_service", "raw_materials_components"],
    },
    "sports_attendance": {
        "entity_slots": ["competition", "team_or_athlete", "venue", "broadcaster", "sponsor"],
        "trigger_types": ["fixture", "ticket_sellout", "record", "tournament_stage", "broadcast_growth"],
        "company_roles": ["event_sponsorship", "platform_service", "distribution", "brand_marketing"],
    },
    "sports_participation": {
        "entity_slots": ["competition", "team", "athlete", "venue", "equipment_or_sponsor"],
        "trigger_types": ["fixture", "result", "record", "selection", "tournament_stage"],
        "company_roles": ["event_sponsorship", "manufacturing_development", "retail_sales", "platform_service"],
    },
    "fashion_collectible": {
        "entity_slots": ["product", "brand", "style_or_ingredient", "creator_or_celebrity", "sales_channel"],
        "trigger_types": ["product_launch", "sellout", "restock", "celebrity_use", "shortform_spread", "collaboration"],
        "company_roles": ["brand_marketing", "manufacturing_development", "raw_materials_components", "retail_sales"],
    },
    "product_brand": {
        "entity_slots": ["product", "brand", "model", "manufacturer", "sales_channel"],
        "trigger_types": ["product_launch", "preorder", "sellout", "price_change", "campaign"],
        "company_roles": ["manufacturing_development", "raw_materials_components", "distribution", "retail_sales"],
    },
    "place_experience": {
        "entity_slots": ["event", "theme", "venue", "date", "organizer_or_participant"],
        "trigger_types": ["ticket_open", "ticket_sellout", "visitor_growth", "limited_product", "speaker_or_artist_announcement", "social_spread"],
        "company_roles": ["event_sponsorship", "platform_service", "distribution", "retail_sales"],
    },
    "lifestyle_behavior": {
        "entity_slots": ["activity", "tool_or_material", "style", "creator_or_community", "sales_channel"],
        "trigger_types": ["participation_growth", "shortform_spread", "class_or_event", "product_demand", "seasonal_return"],
        "company_roles": ["manufacturing_development", "raw_materials_components", "retail_sales", "platform_service"],
    },
    "wellness_behavior": {
        "entity_slots": ["activity", "equipment", "place_or_service", "creator_or_community", "measurement"],
        "trigger_types": ["participation_growth", "challenge", "event", "seasonal_return", "product_demand"],
        "company_roles": ["manufacturing_development", "retail_sales", "platform_service", "brand_marketing"],
    },
    "participation_meme": {
        "entity_slots": ["meme_or_challenge", "originator", "format", "platform", "participating_brand"],
        "trigger_types": ["hashtag_growth", "remix_growth", "creator_spread", "brand_participation", "cross_platform_spread"],
        "company_roles": ["platform_service", "brand_marketing", "content_production", "retail_sales"],
    },
    "public_observation_event": {
        "entity_slots": ["phenomenon", "observation_time", "observation_place", "equipment", "science_platform"],
        "trigger_types": ["observation_window", "forecast", "live_broadcast", "search_growth", "equipment_demand"],
        "company_roles": ["manufacturing_development", "raw_materials_components", "platform_service", "content_production"],
    },
    "technology_tool": {
        "entity_slots": ["technology", "product_or_project", "developer", "component", "application"],
        "trigger_types": ["official_announcement", "product_launch", "investment", "deployment", "regulatory_milestone"],
        "company_roles": ["manufacturing_development", "raw_materials_components", "platform_service", "distribution"],
    },
    "investment_market": {
        "entity_slots": ["asset_or_company", "market", "instrument", "event", "consumer_action"],
        "trigger_types": ["price_move", "listing_event", "filing", "policy_release", "transaction_growth"],
        "company_roles": ["platform_service", "ownership_investment", "distribution", "brand_marketing"],
    },
}


def category_ontology(category: str) -> dict:
    definition = CATEGORY_ONTOLOGY.get(str(category or ""), {})
    return {
        "version": CATEGORY_ONTOLOGY_VERSION,
        "category": str(category or "unclassified"),
        "entity_slots": deepcopy(definition.get("entity_slots", [])),
        "trigger_types": deepcopy(definition.get("trigger_types", [])),
        "recommended_company_roles": deepcopy(definition.get("company_roles", [])),
        "affects_score": False,
    }
