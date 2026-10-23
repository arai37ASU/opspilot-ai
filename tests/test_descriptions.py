import re
from string import Formatter

import numpy as np
import pytest

from opspilot.data_generation import config
from opspilot.data_generation.arrivals import generate_creation_data
from opspilot.data_generation.descriptions import (
    FILL_VALUES,
    TEMPLATES,
    URGENCY_PHRASES,
    VAGUE_DESCRIPTIONS,
    generate_descriptions,
)

# Words that would describe what happened after submission.
OUTCOME_WORDS = re.compile(r"escalat|reopen|again|still|resolved|breach|overdue|days ago|no response", re.IGNORECASE)


@pytest.fixture(scope="module")
def tickets():
    rng = np.random.default_rng(config.DEFAULT_SEED)
    tickets = generate_creation_data(rng)
    tickets["description"] = generate_descriptions(tickets, rng)
    return tickets


def placeholders(template):
    return {field for _, field, _, _ in Formatter().parse(template) if field}


def test_every_subcategory_has_several_templates():
    assert set(TEMPLATES) == set(config.SUBCATEGORIES)
    for subcategory, templates in TEMPLATES.items():
        assert len(templates) >= 3, subcategory


def test_templates_only_use_known_placeholders():
    for templates in TEMPLATES.values():
        for template in templates:
            assert placeholders(template) <= set(FILL_VALUES), template


def test_templates_contain_no_outcome_language():
    all_text = [t for templates in TEMPLATES.values() for t in templates] + VAGUE_DESCRIPTIONS + URGENCY_PHRASES
    for text in all_text:
        assert not OUTCOME_WORDS.search(text), text


def test_every_ticket_gets_a_filled_description(tickets):
    assert tickets["description"].notna().all()
    assert (tickets["description"].str.len() > 0).all()
    assert not tickets["description"].str.contains(r"[{}]").any()


def test_descriptions_are_reproducible(tickets):
    rng = np.random.default_rng(config.DEFAULT_SEED)
    again = generate_creation_data(rng)
    assert generate_descriptions(again, rng).equals(tickets["description"])


def test_vague_share_is_close_to_configured_rate(tickets):
    vague = {text.lower() for text in VAGUE_DESCRIPTIONS}

    def is_vague(description):
        return any(text in description.lower() for text in vague)

    share = tickets["description"].map(is_vague).mean()
    assert abs(share - config.DESCRIPTION_VAGUE_RATE) < 0.01


def test_urgency_wording_is_more_common_for_high_priority(tickets):
    pattern = "|".join(re.escape(p.lower()) for p in URGENCY_PHRASES)
    urgent_text = tickets["description"].str.lower().str.contains(pattern)
    high = tickets["priority"].isin(["P1", "P2"])
    assert urgent_text[high].mean() > 3 * urgent_text[~high].mean()


def test_incident_tickets_mention_a_single_building(tickets):
    buildings = "|".join(re.escape(b.lower()) for b in FILL_VALUES["building"])
    for incident_id in range(len(config.MAJOR_INCIDENTS)):
        text = tickets.loc[tickets["major_incident_id"] == incident_id, "description"].str.lower()
        mentioned = text.str.extract(f"({buildings})")[0].dropna()
        assert mentioned.nunique() <= 1
