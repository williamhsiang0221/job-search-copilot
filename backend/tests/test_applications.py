"""Applications: importing from Notion, backfilling outcomes."""

from datetime import date
from pathlib import Path

import pytest

from app import db
from app.applications_service import (
    ROUND_FROM_PROGRESS,
    apply_from_normalized,
    backfill_summary,
    import_from_tsv,
    list_applications,
    update_application,
)
from app.models import Application, Job, JobNormalized

HEADER = "applied_at\tcompany\trole\ttitle\tjob_id\tprogress\treferral\tsalary_range\n"


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "apps.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def write_tsv(tmp_path, *rows: str) -> Path:
    path = tmp_path / "export.tsv"
    path.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


# ----------------------------------------------------------------- the point

def test_rejections_import_with_an_unknown_round_not_a_guess(fresh_db, tmp_path):
    """Notion's Progress is terminal, so a rejection after a phone screen is
    indistinguishable from one after silence. Recording "applied" would
    fabricate the undercount this column exists to fix."""
    path = write_tsv(
        tmp_path,
        "2026-07-13\tTenex\tStrategist\tAI Strategist\t\tRejected\t\t$140K",
    )
    import_from_tsv(path)

    row = list_applications()[0]
    assert row["status"] == "rejected"
    assert row["highest_round"] is None


def test_withdrawn_is_also_unknown(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-07-01\tAcme\tPM\tPM\t\tWithdrawn\t\t"))
    assert list_applications()[0]["highest_round"] is None


@pytest.mark.parametrize(
    "progress,expected",
    [
        ("Applied", "applied"),
        ("Phone Screen", "phone_screen"),
        ("Interview", "interview"),
        ("Offer", "offer"),
        ("Accepted", "accepted"),
    ],
)
def test_progress_states_that_do_reveal_the_round_are_kept(progress, expected):
    assert ROUND_FROM_PROGRESS[progress] == expected


# ------------------------------------------------------------------- import

def test_import_is_idempotent(fresh_db, tmp_path):
    path = write_tsv(
        tmp_path,
        "2026-08-01\tAcme\tPM\tSenior PM\t\tApplied\t\t",
        "2026-08-02\tBeta\tPM\tPM II\t\tRejected\t\t",
    )
    first = import_from_tsv(path)
    second = import_from_tsv(path)

    assert first["imported"] == 2
    assert second["imported"] == 0
    assert second["skipped_existing"] == 2
    assert len(list_applications()) == 2


def test_same_company_different_roles_are_separate_rows(fresh_db, tmp_path):
    path = write_tsv(
        tmp_path,
        "2026-08-01\tAcme\tPM\tSenior PM\t\tApplied\t\t",
        "2026-08-01\tAcme\tPM\tStaff PM\t\tApplied\t\t",
    )
    import_from_tsv(path)
    assert len(list_applications()) == 2


def test_import_keeps_the_job_id_join_key(fresh_db, tmp_path):
    import_from_tsv(
        write_tsv(tmp_path, "2026-08-01\tAcme\tPM\tSenior PM\t4401277783\tApplied\t\t")
    )
    assert list_applications()[0]["job_id"] == "4401277783"


def test_rows_without_a_company_are_skipped(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-08-01\t\tPM\tSenior PM\t\tApplied\t\t"))
    assert list_applications() == []


def test_unparseable_date_does_not_lose_the_row(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "not-a-date\tAcme\tPM\tPM\t\tApplied\t\t"))
    rows = list_applications()
    assert len(rows) == 1
    assert rows[0]["applied_at"] is None


# --------------------------------------------------------- apply_from_normalized

def test_apply_from_normalized_matches_by_source(fresh_db):
    """A job id is only unique within its own source, so apply must be told
    which source a normalized job belongs to rather than assuming linkedin."""
    with db.session_scope() as session:
        session.add(Job(source="greenhouse", job_id="1", title="Senior PM", company="Duolingo"))
        session.add(JobNormalized(source="greenhouse", job_id="1", title="Senior PM", company="Duolingo"))

    report = apply_from_normalized(["1"], source="greenhouse")
    assert report["applied"] == ["1"]
    assert list_applications()[0]["company"] == "Duolingo"


def test_apply_from_normalized_does_not_cross_sources(fresh_db):
    """The regression this guards: passing the wrong source must not find a
    job normalized under a different one, and must not silently no-op as if
    it had applied."""
    with db.session_scope() as session:
        session.add(Job(source="greenhouse", job_id="1", title="Senior PM", company="Duolingo"))
        session.add(JobNormalized(source="greenhouse", job_id="1", title="Senior PM", company="Duolingo"))

    report = apply_from_normalized(["1"], source="linkedin")
    assert report["applied"] == []
    assert report["skipped_missing"] == ["1"]
    assert list_applications() == []


def test_apply_from_normalized_skips_existing(fresh_db):
    with db.session_scope() as session:
        session.add(Job(source="greenhouse", job_id="1", title="PM", company="Acme"))
        session.add(JobNormalized(source="greenhouse", job_id="1", title="PM", company="Acme"))

    first = apply_from_normalized(["1"], source="greenhouse")
    assert first["applied"] == ["1"]

    second = apply_from_normalized(["1"], source="greenhouse")
    assert second["applied"] == []
    assert second["skipped_existing"] == ["1"]


# ----------------------------------------------------------------- backfill

def test_backfill_updates_the_summary(fresh_db, tmp_path):
    import_from_tsv(
        write_tsv(
            tmp_path,
            "2026-08-01\tAcme\tPM\tSenior PM\t\tApplied\t\t",
            "2026-07-13\tTenex\tStrategist\tAI Strategist\t\tRejected\t\t",
        )
    )
    before = backfill_summary()
    assert (before["known"], before["needs_backfill"]) == (1, 1)

    tenex = next(a for a in list_applications() if a["company"] == "Tenex")
    update_application(tenex["id"], {"highest_round": "phone_screen"})

    after = backfill_summary()
    assert (after["known"], after["needs_backfill"]) == (2, 0)
    assert after["reached_past_applied"] == 1


def test_response_rate_excludes_unknowns_rather_than_counting_them_as_failures(
    fresh_db, tmp_path
):
    """Counting unknowns as failures would repeat the original mistake in the
    other direction."""
    import_from_tsv(
        write_tsv(
            tmp_path,
            "2026-08-01\tAcme\tPM\tA\t\tPhone Screen\t\t",
            "2026-08-02\tBeta\tPM\tB\t\tRejected\t\t",
            "2026-08-03\tGamma\tPM\tC\t\tRejected\t\t",
        )
    )
    summary = backfill_summary()
    # 1 of 1 known reached past applied — the two unknowns are excluded.
    assert summary["known"] == 1
    assert summary["response_rate_of_known"] == 100.0


def test_an_unknown_round_can_be_set_back_to_unknown(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-08-01\tAcme\tPM\tA\t\tPhone Screen\t\t"))
    row = list_applications()[0]

    update_application(row["id"], {"highest_round": None})
    assert list_applications()[0]["highest_round"] is None


def test_invalid_round_is_rejected(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-08-01\tAcme\tPM\tA\t\tApplied\t\t"))
    row = list_applications()[0]

    with pytest.raises(ValueError, match="unknown round"):
        update_application(row["id"], {"highest_round": "coffee_chat"})


def test_updating_a_missing_application_returns_none(fresh_db):
    assert update_application(9999, {"highest_round": "offer"}) is None


def test_only_editable_fields_are_writable(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-08-01\tAcme\tPM\tSenior PM\t\tApplied\t\t"))
    row = list_applications()[0]

    update_application(row["id"], {"salary_range": "Hacked", "highest_round": "offer"})

    after = list_applications()[0]
    assert after["salary_range"] is None
    assert after["highest_round"] == "offer"


def test_company_and_title_are_editable(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-08-01\tAcme\tPM\tSenior PM\t\tApplied\t\t"))
    row = list_applications()[0]

    update_application(row["id"], {"company": "  New Co  ", "title": "  Staff PM  "})

    after = list_applications()[0]
    assert after["company"] == "New Co"
    assert after["title"] == "Staff PM"


def test_blank_company_is_rejected(fresh_db, tmp_path):
    import_from_tsv(write_tsv(tmp_path, "2026-08-01\tAcme\tPM\tSenior PM\t\tApplied\t\t"))
    row = list_applications()[0]

    with pytest.raises(ValueError, match="blank"):
        update_application(row["id"], {"company": "   "})


def test_empty_database_summarizes_without_dividing_by_zero(fresh_db):
    summary = backfill_summary()
    assert summary["total"] == 0
    assert summary["response_rate_of_known"] is None
