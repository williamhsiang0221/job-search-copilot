"""Workday's list endpoint gives relative posted-date text, unlike the other
three ATSes' timestamps — the one genuinely new piece of parsing logic
Workday support needed, so the one piece worth unit testing here. The HTTP
fetch/list/parse flows themselves follow the same live-verification approach
already used for Greenhouse/Ashby/Lever, which have no mocked tests either.
"""

from datetime import date

import pytest

from app import ats_service
from app.ats_service import _parse_workday_relative_date, _passes_filter
from app.jd_sources import OracleSource, parse_oracle_token

TODAY = date(2026, 9, 25)


@pytest.mark.parametrize(
    "location",
    [
        "New York, NY",
        "NYC",
        "Remote - US",
        "Plano, TX, United States; New York, NY, United States",
        "",
    ],
)
def test_location_keywords_pass(location):
    assert _passes_filter("Product Manager", location, TODAY, TODAY)


@pytest.mark.parametrize(
    "location",
    ["San Francisco, CA", "Seattle, WA", "Los Angeles, CA", "Chicago, IL", "Bellevue, Washington"],
)
def test_locations_outside_new_york_are_dropped(location):
    assert not _passes_filter("Product Manager", location, TODAY, TODAY)


@pytest.mark.parametrize(
    "text, expected",
    [("2 Locations", ""), ("14 Locations", ""), ("New York, New York", "New York, New York"), (None, "")],
)
def test_workday_multi_location_placeholder_is_unstated(text, expected):
    assert ats_service._workday_location(text) == expected


# Real titles from a dry scan of the tracked boards.
@pytest.mark.parametrize(
    "title",
    [
        "Senior Product Manager, Growth",
        "Director of Product Management, Advertiser Growth",
        "Associate Manager, Product Marketing",
        "Lifecycle Marketing Manager, Capital",
        "Senior Manager, User Acquisition",
        "Marketing Analytics Lead, Enterprise Marketing",
        "Data Analyst, NYC",
        "Manager, Analytics, Customer Experience",
        "Data Scientist, Experimentation",
        "Strategist, Agent Development - Healthcare",
        "Engagement Manager, AI Deployment",
        "Forward Deployed AI Accelerator, Marketing",
        "GTM Strategy & Operations Analyst",
        "Business Operations, Growth",
        # Bank-style titles (JPMC)
        "Senior Product Associate, Merchant Experience - Offers & Shopping",
        "Product Owner - Unstructured Data & AI",
        "Product Director - Manage & Service",
        "Senior Associate, Marketing Strategy (Offers & Shopping)",
        "Senior Associate, Customer Engagement Marketing",
        "Vice President — Card Acquisition  Strategy, Offers & Channel  Optimization",
    ],
)
def test_title_filter_keeps_target_roles(title):
    assert _passes_filter(title, "", TODAY, TODAY)


@pytest.mark.parametrize(
    "title",
    [
        "Forward Deployed Engineer, Privy",
        "Staff Product Designer, Growth",
        "Solutions Architect, Enterprise (Presales)",
        "Account Executive, Product Sales - Billing",
        "Product Management Intern",
        "Strategy & Operations, Risk",  # S&O without a growth/GTM/AI qualifier
        "Staff Data Scientist, Forecasting",  # data science without a qualifier
        "Financial Analyst II, FP&A",
        "Maintenance Technician",  # "ai" must match a whole word
    ],
)
def test_title_filter_drops_off_target_roles(title):
    assert not _passes_filter(title, "", TODAY, TODAY)


def test_posted_today():
    assert _parse_workday_relative_date("Posted Today", TODAY) == TODAY


def test_posted_yesterday():
    assert _parse_workday_relative_date("Posted Yesterday", TODAY) == date(2026, 9, 24)


def test_posted_n_days_ago():
    assert _parse_workday_relative_date("Posted 3 Days Ago", TODAY) == date(2026, 9, 22)


def test_posted_n_plus_days_ago():
    assert _parse_workday_relative_date("Posted 30+ Days Ago", TODAY) == date(2026, 8, 26)


def test_unrecognized_text_is_not_a_date():
    assert _parse_workday_relative_date("Something unexpected", TODAY) is None


def test_missing_text_is_not_a_date():
    assert _parse_workday_relative_date(None, TODAY) is None


# --- Oracle Recruiting Cloud -------------------------------------------------
# Field shapes below are copied from live JPMC and American Express responses.


def test_oracle_token_with_and_without_categories():
    assert parse_oracle_token("egug.fa.us2.oraclecloud.com/CX_1") == (
        "egug.fa.us2.oraclecloud.com", "CX_1", "",
    )
    assert parse_oracle_token("jpmc.fa.oraclecloud.com/CX_1001/111;222") == (
        "jpmc.fa.oraclecloud.com", "CX_1001", "111;222",
    )
    with pytest.raises(ValueError):
        parse_oracle_token("jpmc.fa.oraclecloud.com")


def _oracle_job(job_id, posted, location="New York, NY, United States", secondary=()):
    return {
        "Id": job_id,
        "Title": "Product Manager",
        "PostedDate": posted,
        "PrimaryLocation": location,
        "secondaryLocations": [{"Name": name} for name in secondary],
    }


def test_oracle_list_stops_at_cutoff_and_folds_in_secondary_locations(monkeypatch):
    today = date.today().isoformat()
    finders = []
    pages = [
        {"requisitionList": [_oracle_job(str(i), today) for i in range(100)]},
        {
            "requisitionList": [
                _oracle_job("200", today, "Plano, TX, United States", ["New York, NY, United States"]),
                _oracle_job("201", "2020-01-01"),
            ]
            + [_oracle_job(str(300 + i), "2020-01-01") for i in range(98)]
        },
        {"requisitionList": [_oracle_job("999", today)]},  # never reached
    ]

    def fake_requisitions(host, finder):
        finders.append(finder)
        if "facetsList=LOCATIONS" in finder:
            return {"locationsFacet": [{"Id": 42, "Name": "United States"}]}
        return pages[len(finders) - 2]

    monkeypatch.setattr(ats_service, "_oracle_requisitions", fake_requisitions)
    monkeypatch.setattr(ats_service.time, "sleep", lambda _: None)

    jobs = ats_service._list_oracle("jpmc.fa.oraclecloud.com/CX_1001/111;222")

    assert len(finders) == 3  # US lookup + two pages; the stale page ends it
    assert "locationId=42" in finders[1]
    assert "selectedCategoriesFacet=111;222" in finders[1]
    assert "sortBy=POSTING_DATES_DESC" in finders[1]
    assert "offset=100" in finders[2]
    secondary = next(j for j in jobs if j["job_id"] == "200")
    assert secondary["location"] == "Plano, TX, United States; New York, NY, United States"
    assert secondary["url"] == (
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/200"
    )


def test_oracle_detail_joins_description_fields_and_reads_pay_flex_field():
    job = OracleSource(job_companies={"26013862": "American Express"})._parse(
        "26013862",
        "egug.fa.us2.oraclecloud.com",
        "CX_1",
        {
            "Title": "Senior Manager - Digital Product Management",
            "ExternalPostedStartDate": "2026-09-30T00:18:19+00:00",
            "ExternalDescriptionStr": "<p>About the team</p>",
            "ExternalResponsibilitiesStr": "<ul><li>Own the roadmap</li></ul>",
            "ExternalQualificationsStr": "<p>5+ years</p>",
            "CorporateDescriptionStr": "<p>Company boilerplate</p>",
            "PrimaryLocation": "New York, NY, United States",
            "JobSchedule": "Full time",
            "WorkplaceType": "Hybrid",
            "Category": "Product",
            "requisitionFlexFields": [
                {"Prompt": "Salary Range", "Value": "$123000 - $215250 annually"},
            ],
        },
    )
    assert job.company == "American Express"
    assert job.description_raw == "About the team\n\nOwn the roadmap\n\n5+ years"
    assert job.salary_text == "$123000 - $215250 annually"
    assert job.workplace_raw == "hybrid"
    assert job.posted_at == date(2026, 9, 30)
    assert job.url.endswith("/sites/CX_1/job/26013862")
