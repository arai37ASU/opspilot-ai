"""The number guard: invented numbers must be caught, honest rounding must not be."""

import pytest

from opspilot.ai.grounding import unsupported_numbers

FACTS = {
    "created": "Wednesday 03 September 2025 at 19:30",
    "risk": "98%",
    "review": "about 10%",
    "reasons": [{"label": "Team's breach rate, last 30 days", "value": "18.0%"},
                {"label": "Hours until staffed", "value": "12.5 hours"},
                {"label": "Resolved tickets", "value": "1,139"},
                {"label": "Priority", "value": "P2"}],
}


@pytest.mark.parametrize("text", [
    "The risk is 98%.",
    "The team breached 18.0% of tickets over the last 30 days.",
    "The team breached 18% of tickets.",
    "The team is unstaffed for 12.5 hours, or about 13 hours.",
    "It has resolved 1,139 tickets, and 1139 is a healthy history.",
    "It arrived at 19:30 on September 3, 2025.",
    "Reviews are limited to 10 percent of tickets.",
    "As a P2 ticket it has a tight target.",
    "One of the main reasons is that two things stack up.",
])
def test_supported_text_passes(text):
    assert unsupported_numbers(text, FACTS) == []


@pytest.mark.parametrize("text, caught", [
    ("The risk is 95%.", "95%"),
    ("The team breached 19% of tickets.", "19"),  # 19 appears only in the time 19:30
    ("The team breached 18 tickets.", "18"),  # the fact is 18.0%, a percentage
    ("It will wait 12.5% longer.", "12.5"),  # the fact is 12.5 hours
    ("It arrived at 19:45.", "19:45"),
    ("The team breached 19 percent of tickets.", "19"),
    ("It will wait 14 hours.", "14"),
    ("Resolved 1,140 tickets.", "1,140"),
    ("Risk is 80 points above the threshold.", "80"),
    ("It is expected to take eight hours.", "eight"),
    ("Risk is twice the threshold.", "twice"),
    ("About half of such tickets breach.", "half"),
    ("Nineteen tickets are waiting.", "Nineteen"),
])
def test_invented_numbers_are_caught(text, caught):
    found = unsupported_numbers(text, FACTS)
    assert found and caught.rstrip("%") in found[0]


def test_a_number_inside_an_identifier_is_not_a_quantity():
    assert unsupported_numbers("Ticket P4 on channel L7", FACTS) == []
