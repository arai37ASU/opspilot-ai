"""Briefing facts and checks, with a fake Claude client: no network and no cost."""

from datetime import date

import pytest

from conftest import FakeClient, reply
from opspilot.ai.briefing import Briefer, BriefingDraft, Finding, briefing_facts, draft_problems, year_earlier

LAST_DAY = date(2025, 12, 31)


def period(start=date(2025, 3, 1), end=date(2025, 3, 31), tickets=2300, rate=16.4):
    return {"start": start, "end": end, "tickets": tickets, "resolved": 2280, "breached": 374, "unresolved": 0,
            "breach_rate_pct": rate, "median_resolution_hours": 17.3, "mean_satisfaction": 3.99,
            "by_priority": [{"priority": "P1", "resolved": 50, "breach_rate_pct": 42.0}]}


TEAMS = [
    {"team": "Service Desk", "tickets": 500, "breach_rate_pct": 3.1, "median_resolution_hours": 14.4, "misrouted_pct": 2.8},
    {"team": "Network Operations", "tickets": 300, "breach_rate_pct": 25.2, "median_resolution_hours": 16.0, "misrouted_pct": 4.9},
]


def facts(**kwargs):
    return briefing_facts(period(**kwargs), period(date(2024, 3, 1), date(2024, 3, 31), 2200, 15.1), TEAMS, [], [], LAST_DAY)


def draft(headline="Breaches were 16.4% this month.", findings=None, actions=("Review the Network Operations queue.",)):
    if findings is None:
        findings = [Finding(text="Network Operations breached 25.2% of tickets.", sources=["by_team"]),
                    Finding(text="Tickets are up 100 on last year.", sources=["comparison"])]
    return BriefingDraft(headline=headline, findings=findings, actions=list(actions))


def test_a_good_draft_passes():
    assert draft_problems(draft(), facts()) == []


def test_a_finding_cannot_borrow_a_number_from_a_section_it_does_not_cite():
    # 25.2% is a real fact, but it belongs to by_team, not by_priority.
    borrowed = Finding(text="P1 tickets breached 25.2% of the time.", sources=["by_priority"])
    problems = draft_problems(draft(findings=[borrowed, draft().findings[0]]), facts())
    assert problems == ["'25.2%' is not in the sections its finding cites: by_priority"]


def test_an_invented_number_is_rejected_everywhere():
    assert draft_problems(draft(headline="Breaches were 12%."), facts())
    assert draft_problems(draft(actions=["Cut the backlog by 30%."]), facts())


@pytest.mark.parametrize("sources", [[], ["comparison"]])
def test_a_finding_must_cite_a_section_that_exists(sources):
    without_comparison = briefing_facts(period(), None, TEAMS, [], [], LAST_DAY)
    finding = Finding(text="Tickets were steady.", sources=sources)
    assert any("must cite" in p for p in draft_problems(draft(findings=[finding, finding]), without_comparison))


def test_the_number_of_findings_and_actions_is_limited():
    one = Finding(text="Steady.", sources=["overview"])
    assert any("findings" in p for p in draft_problems(draft(findings=[one]), facts()))
    assert any("findings" in p for p in draft_problems(draft(findings=[one] * 5), facts()))
    assert any("actions" in p for p in draft_problems(draft(actions=[]), facts()))


def test_changes_are_computed_for_claude():
    comparison = facts()["comparison"]
    assert comparison["tickets_change"] == "up 100"
    assert comparison["breach_rate_change"] == "up 1.3 percentage points"


def test_teams_are_ordered_worst_first():
    assert [team["team"] for team in facts()["by_team"]] == ["Network Operations", "Service Desk"]


def test_a_period_with_no_resolved_tickets_is_not_shown_as_zero():
    built = briefing_facts(period(rate=None), None, [], [], [], LAST_DAY)
    assert built["overview"]["breach_rate"] == "not available"


def test_year_earlier_handles_a_leap_day_and_the_start_of_the_data():
    first = date(2024, 1, 1)
    assert year_earlier(date(2025, 3, 1), date(2025, 3, 31), first) == (date(2024, 3, 1), date(2024, 3, 31))
    assert year_earlier(date(2024, 2, 29), date(2024, 3, 1), date(2023, 1, 1)) == (date(2023, 2, 28), date(2023, 3, 1))
    assert year_earlier(date(2024, 3, 1), date(2024, 3, 31), first) is None


def test_briefer_returns_code_written_caveats_with_the_text():
    built = facts(end=date(2025, 12, 31))
    assert built["caveats"]
    result = Briefer(FakeClient(reply(draft())), "claude-test").brief(built)
    assert result["caveats"] == built["caveats"]
    assert result["facts"] == built
    assert result["findings"][0]["sources"] == ["by_team"]


def test_briefer_retries_a_rejected_draft_with_the_problem_named():
    client = FakeClient(reply(draft(headline="Breaches were 99%.")), reply(draft()))
    result = Briefer(client, "claude-test").brief(facts())
    assert result["attempts"] == 2
    assert "'99%'" in client.requests[1]["messages"][0]["content"]


def test_caveats_do_not_contradict_each_other():
    from opspilot.ai.briefing import caveats_for

    no_comparison = caveats_for(LAST_DAY, LAST_DAY, has_comparison=False)
    assert len(no_comparison) == 2
    assert not any("not compared with last year" in caveat for caveat in no_comparison)
    assert any("not compared with last year" in caveat for caveat in caveats_for(LAST_DAY, LAST_DAY, has_comparison=True))
