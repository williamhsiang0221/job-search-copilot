"""Parser tests run against real LinkedIn emails captured into fixtures/."""

from pathlib import Path

import pytest

from app.parser import parse_email_body

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def digest_roles():
    return parse_email_body(load("alert_digest.txt"), subject="martech alert")


@pytest.fixture(scope="module")
def recommendation_roles():
    return parse_email_body(load("recommendations.txt"), subject="Bloomberg TPM")


def test_digest_finds_every_job(digest_roles):
    assert len(digest_roles) == 6


def test_recommendations_find_every_job(recommendation_roles):
    assert len(recommendation_roles) == 6


def test_header_preamble_does_not_leak_into_first_row(digest_roles):
    """The first block also holds the email header; it must not become a row."""
    first = digest_roles[0]
    assert first.title == "Associate Director, Digital Product Management – AI Orchestration"
    assert first.company == "Digitas North America"
    assert first.location == "New York, NY"


def test_badge_lines_do_not_shift_fields(digest_roles):
    """Duolingo's block has a badge with no blank line before it."""
    duolingo = next(r for r in digest_roles if r.company == "Duolingo")
    assert duolingo.title == "Senior Product Manager, Notifications"
    assert duolingo.location == "New York, NY"


def test_badge_above_view_job_in_recommendations(recommendation_roles):
    traba = next(r for r in recommendation_roles if r.company == "Traba")
    assert traba.title == "Senior Product Manager (AI Agents)"
    assert traba.location == "New York"


def test_tracking_params_are_stripped(digest_roles):
    for role in digest_roles:
        assert role.url == f"https://www.linkedin.com/jobs/view/{role.job_id}/"
        assert "trackingId" not in role.url
        assert "midToken" not in role.url


def test_job_ids_are_numeric_and_unique(digest_roles):
    ids = [r.job_id for r in digest_roles]
    assert all(i.isdigit() for i in ids)
    assert len(set(ids)) == len(ids)


def test_non_ascii_company_survives(recommendation_roles):
    assert any(r.company == "The Estée Lauder Companies Inc." for r in recommendation_roles)


def test_footer_and_see_all_jobs_are_not_rows(digest_roles):
    companies = {r.company for r in digest_roles}
    assert not any("LinkedIn Corporation" in c for c in companies)
    assert all("See all jobs" not in r.title for r in digest_roles)


def test_empty_body_yields_nothing():
    assert parse_email_body("") == []


def test_body_without_job_links_yields_nothing():
    assert parse_email_body("Your posts got 11 impressions last week.\n\n---\n\nfooter") == []


@pytest.fixture(scope="module")
def saved_job_roles():
    return parse_email_body(load("saved_job_reminder.txt"), subject="apply now reminder")


def test_saved_job_reminder_finds_both_jobs(saved_job_roles):
    assert len(saved_job_roles) == 2


def test_section_header_does_not_shift_fields(saved_job_roles):
    """Regression: "Your other saved jobs" sits directly above the title with no
    blank line, and previously became the title, shifting every field by one."""
    first = saved_job_roles[0]
    assert first.title == "Product Manager - UX, AI Workflows"
    assert first.company == "Comcast"
    assert first.location == "New York, New York, United States"


def test_apply_now_cta_link_is_not_a_job_row(saved_job_roles):
    """The bare "Apply now" URL at the top has no "View job:" line, so it must
    not produce a row of its own."""
    assert "4443512216" not in {r.job_id for r in saved_job_roles}


def test_second_job_in_reminder_is_clean(saved_job_roles):
    second = saved_job_roles[1]
    assert second.company == "JPMorganChase"
    assert second.title.startswith("Product Manager - Personalization")


def test_dedupe_collapses_repeats_and_counts_them():
    from app.parser import dedupe_roles

    roles = parse_email_body(load("alert_digest.txt")) + parse_email_body(
        load("alert_digest.txt")
    )
    assert len(roles) == 12

    deduped = dedupe_roles(roles)
    assert len(deduped) == 6
    assert all(r.match_count == 2 for r in deduped)


def test_dedupe_keeps_distinct_jobs_apart():
    from app.parser import dedupe_roles

    roles = parse_email_body(load("alert_digest.txt")) + parse_email_body(
        load("recommendations.txt")
    )
    deduped = dedupe_roles(roles)
    assert len({r.job_id for r in deduped}) == len(deduped)
    assert len(deduped) == 12  # no overlap between these two fixtures


def test_dedupe_prefers_the_more_specific_location():
    """The same job arrives as "New York" in one alert and "New York, NY" in
    another; the longer string is the more useful one to show."""
    from app.parser import Role, dedupe_roles

    base = dict(title="PM", company="Acme", url="u", job_id="1")
    roles = [Role(location="New York", **base), Role(location="New York, NY", **base)]

    deduped = dedupe_roles(roles)
    assert len(deduped) == 1
    assert deduped[0].location == "New York, NY"
    assert deduped[0].match_count == 2


def test_dedupe_preserves_first_seen_order():
    from app.parser import Role, dedupe_roles

    roles = [
        Role(title="A", company="A", location="", url="", job_id="3"),
        Role(title="B", company="B", location="", url="", job_id="1"),
        Role(title="C", company="C", location="", url="", job_id="3"),
    ]
    assert [r.job_id for r in dedupe_roles(roles)] == ["3", "1"]


def test_dedupe_of_empty_list():
    from app.parser import dedupe_roles

    assert dedupe_roles([]) == []


def test_dedupe_keeps_the_latest_received_date():
    """The column answers "when did this job last appear", so a repeat carried
    by a newer alert must win over the copy encountered first."""
    from app.parser import Role, dedupe_roles

    base = dict(title="PM", company="Acme", location="NY", url="u", job_id="1")
    roles = [
        Role(received_at="2026-08-20T09:00:00+00:00", **base),
        Role(received_at="2026-08-26T17:51:12+00:00", **base),
        Role(received_at="2026-08-22T11:00:00+00:00", **base),
    ]

    deduped = dedupe_roles(roles)
    assert len(deduped) == 1
    assert deduped[0].received_at == "2026-08-26T17:51:12+00:00"
    assert deduped[0].match_count == 3


def test_dedupe_tolerates_a_missing_date():
    from app.parser import Role, dedupe_roles

    base = dict(title="PM", company="Acme", location="NY", url="u", job_id="1")
    roles = [Role(received_at="", **base), Role(received_at="2026-08-26T00:00:00+00:00", **base)]
    assert dedupe_roles(roles)[0].received_at == "2026-08-26T00:00:00+00:00"
