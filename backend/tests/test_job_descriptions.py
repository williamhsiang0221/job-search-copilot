"""Job description fetching, storage and normalization."""

from datetime import date
from pathlib import Path

import pytest

from app import db
from app.jd_sources import (
    FetchedJob,
    JobDescriptionError,
    fetch_many,
    resolve_posted_at,
)
from app.models import Evaluation, Job, JobNormalized
from app.normalizer import NormalizedJob, NormalizerUnavailable, _clean

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TODAY = date(2026, 8, 27)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


# --------------------------------------------------------------- posted_at

@pytest.mark.parametrize(
    "text,expected_days_back",
    [
        ("3 hours ago", 1),
        ("1 day ago", 1),
        ("5 days ago", 5),
        ("1 week ago", 7),
    ],
)
def test_recent_postings_resolve_precisely(text, expected_days_back):
    resolved, approximate = resolve_posted_at(text, TODAY)
    assert (TODAY - resolved).days == expected_days_back
    # LinkedIn never states a real date, so nothing from it is exact.
    assert approximate is True


@pytest.mark.parametrize(
    "text",
    ["2 weeks ago", "3 months ago", "1 year ago", "30+ days ago", "gibberish"],
)
def test_anything_older_than_a_week_buckets_to_30_days(text):
    resolved, _ = resolve_posted_at(text, TODAY)
    assert (TODAY - resolved).days == 30


def test_reposted_buckets_regardless_of_how_recent():
    """A repost date says when it was reposted, not when the role opened."""
    resolved, _ = resolve_posted_at("Reposted 2 days ago", TODAY)
    assert (TODAY - resolved).days == 30


def test_missing_posting_text_gives_no_date():
    assert resolve_posted_at("", TODAY) == (None, True)


# ------------------------------------------------------------ batch behaviour

class FakeSource:
    name = "linkedin"

    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.calls = []

    def fetch(self, job_id):
        self.calls.append(job_id)
        if job_id in self.fail_on:
            raise JobDescriptionError("simulated failure")
        return FetchedJob(
            source=self.name,
            job_id=job_id,
            title=f"Role {job_id}",
            company="Example Corp",
            description_raw="Responsibilities: ship things.",
            posted_at=TODAY,
        )


def test_one_failure_does_not_abort_the_batch():
    source = FakeSource(fail_on={"b"})
    fetched, failures = fetch_many(source, ["a", "b", "c"], delay_seconds=0)

    assert [f.job_id for f in fetched] == ["a", "c"]
    assert set(failures) == {"b"}
    assert source.calls == ["a", "b", "c"]


def test_on_progress_fires_for_every_id_including_failures():
    """Drives the frontend's live "N of M" progress bar — a failed id must
    still be reported, or a batch with any failure would never reach 100%."""
    source = FakeSource(fail_on={"b"})
    seen = []
    fetch_many(source, ["a", "b", "c"], delay_seconds=0, on_progress=seen.append)

    assert seen == ["a", "b", "c"]


# ------------------------------------------------------------------ storage

def test_same_id_from_two_sources_stays_two_rows(fresh_db):
    """Job ids are only unique within a source, hence the composite key."""
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="8101310", title="A", company="X"))
        session.add(Job(source="greenhouse", job_id="8101310", title="B", company="Y"))

    with db.session_scope() as session:
        assert session.query(Job).count() == 2


def test_descriptions_are_stored_even_when_normalization_fails(fresh_db, monkeypatch):
    """Refetching costs a request to an undocumented endpoint; re-normalizing
    is a cheap local retry. So the description is kept either way.

    The outage is simulated rather than relying on there being no API key —
    otherwise this passes for the wrong reason on a machine with credentials,
    and makes a real API call on one without.
    """
    import app.jobs_service as service
    from app.jobs_service import fetch_and_store, ready_job_ids

    def unavailable(*args, **kwargs):
        raise NormalizerUnavailable("simulated outage")

    monkeypatch.setattr(service, "normalize", unavailable)

    report = fetch_and_store(["a", "b"], source=FakeSource(), delay_seconds=0)

    assert set(report.stored) == {"a", "b"}
    assert report.normalized == []
    assert set(report.normalize_failures) == {"a", "b"}

    with db.session_scope() as session:
        assert session.query(Job).count() == 2
        assert session.query(JobNormalized).count() == 0

    # Not ready, so the UI keeps them selectable for a retry.
    assert ready_job_ids("linkedin", ["a", "b"]) == set()


def test_readiness_tracks_normalized_rows_not_stored_ones(fresh_db):
    from app.jobs_service import ready_job_ids

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="A", company="X"))
        session.add(Job(source="linkedin", job_id="b", title="B", company="X"))
        session.add(JobNormalized(source="linkedin", job_id="b", title="B", company="X"))

    assert ready_job_ids("linkedin", ["a", "b"]) == {"b"}


def test_already_normalized_jobs_are_skipped_not_refetched(fresh_db, monkeypatch):
    import app.jobs_service as service
    from app.jobs_service import fetch_and_store

    monkeypatch.setattr(service, "normalize", lambda *a, **k: (_ for _ in ()).throw(
        NormalizerUnavailable("no model in tests")
    ))

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="A", company="X"))
        session.add(JobNormalized(source="linkedin", job_id="a", title="A", company="X"))

    source = FakeSource()
    report = fetch_and_store(["a", "b"], source=source, delay_seconds=0)

    assert report.skipped == ["a"]
    assert source.calls == ["b"]  # "a" never hit the network


def test_on_progress_reports_skipped_ids_immediately(fresh_db, monkeypatch):
    """A skipped id resolves without ever reaching fetch_many, so it needs its
    own progress signal — otherwise a batch that is all-skipped would leave a
    caller's progress bar stuck at 0."""
    import app.jobs_service as service
    from app.jobs_service import fetch_and_store

    monkeypatch.setattr(service, "normalize", lambda *a, **k: (_ for _ in ()).throw(
        NormalizerUnavailable("no model in tests")
    ))

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="A", company="X"))
        session.add(JobNormalized(source="linkedin", job_id="a", title="A", company="X"))

    seen = []
    fetch_and_store(["a", "b"], source=FakeSource(), delay_seconds=0, on_progress=seen.append)

    assert set(seen) == {"a", "b"}


def test_duplicate_ids_in_one_request_are_fetched_once(fresh_db, monkeypatch):
    import app.jobs_service as service
    from app.jobs_service import fetch_and_store

    monkeypatch.setattr(service, "normalize", lambda *a, **k: (_ for _ in ()).throw(
        NormalizerUnavailable("no model in tests")
    ))

    source = FakeSource()
    fetch_and_store(["a", "a", "a"], source=source, delay_seconds=0)
    assert source.calls == ["a"]


# --------------------------------------------------------------- normalizer

def test_missing_values_stay_missing_rather_than_being_guessed():
    """Absence is information: the evaluator must be able to tell "not stated"
    from a real figure."""
    cleaned = _clean(NormalizedJob(responsibilities=["Ship"], qualifications=["5 years"]))
    assert cleaned.comp_min is None
    assert cleaned.comp_max is None
    assert cleaned.workplace is None


def test_reversed_compensation_range_is_ordered():
    cleaned = _clean(NormalizedJob(comp_min=220000, comp_max=180000))
    assert (cleaned.comp_min, cleaned.comp_max) == (180000, 220000)


def test_unrecognised_workplace_value_is_dropped_not_kept():
    assert _clean(NormalizedJob(workplace="flexible")).workplace is None
    assert _clean(NormalizedJob(workplace="  Remote ")).workplace == "remote"


def test_blank_list_entries_are_removed():
    cleaned = _clean(NormalizedJob(qualifications=["  7+ years ", "", "   "]))
    assert cleaned.qualifications == ["7+ years"]


def test_empty_description_is_not_sent_to_the_model():
    with pytest.raises(NormalizerUnavailable, match="nothing to normalize"):
        from app.normalizer import normalize

        normalize("   ")


# ---------------------------------------------------- normalizer call shape

class FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return type("Response", (), {"parsed_output": self.payload})()


class FakeAnthropic:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_normalize_sends_the_description_and_returns_cleaned_fields():
    """Exercises the call shape without credentials, so a signature change in
    the SDK fails here rather than at the first real fetch."""
    from app.normalizer import normalize

    client = FakeAnthropic(
        NormalizedJob(
            responsibilities=[" Own the roadmap "],
            qualifications=["7+ years"],
            comp_min=220000,
            comp_max=180000,
            workplace="REMOTE",
        )
    )

    # Pinned to v1 rather than the configured default: this test is about the
    # SDK call shape, not which prompt version happens to be current.
    result = normalize(
        "Some description", title="Staff PM", company="Example Corp", client=client, prompt_version="v1"
    )

    sent = client.messages.kwargs
    assert sent["output_format"] is NormalizedJob
    assert "Some description" in sent["messages"][0]["content"]
    assert "Staff PM" in sent["messages"][0]["content"]
    assert sent["system"].startswith("You extract structured fields")

    # Cleaning is applied to whatever the model returned.
    assert result.normalized.responsibilities == ["Own the roadmap"]
    assert (result.normalized.comp_min, result.normalized.comp_max) == (180000, 220000)
    assert result.normalized.workplace == "remote"


def test_normalize_records_token_usage_and_cost():
    """Same usage/cost capture evaluate() already does, mirrored here so a
    normalize call is no longer invisible to the cost total."""
    from app.normalizer import normalize

    class FakeMessagesWithUsage(FakeMessages):
        def parse(self, **kwargs):
            self.kwargs = kwargs
            usage = type("Usage", (), {"input_tokens": 1000, "output_tokens": 200})()
            return type("Response", (), {"parsed_output": self.payload, "usage": usage})()

    client = FakeAnthropic(NormalizedJob())
    client.messages = FakeMessagesWithUsage(NormalizedJob())

    result = normalize("Some description", client=client, model="claude-haiku-4-5")

    assert result.input_tokens == 1000
    assert result.output_tokens == 200
    # claude-haiku-4-5 is $1.00/$5.00 per million: 1000*1.0 + 200*5.0 = 2000, /1e6.
    assert result.cost_usd == 0.002


def test_normalize_defaults_to_the_configured_prompt_version_and_stamps_it():
    """Same versioning discipline as the evaluator's rubric_version — a
    result must say which prompt wording produced it."""
    from app.normalizer import normalize

    client = FakeAnthropic(NormalizedJob())
    result = normalize("Some description", client=client)

    from app import config

    assert result.prompt_version == config.NORMALIZER_PROMPT_VERSION


def test_normalize_uses_the_requested_prompt_version_verbatim():
    from app.normalizer import load_prompt, normalize

    client = FakeAnthropic(NormalizedJob())
    result = normalize("Some description", client=client, prompt_version="v1")

    assert result.prompt_version == "v1"
    assert client.messages.kwargs["system"] == load_prompt("v1")


def test_unknown_prompt_version_raises_normalizer_unavailable():
    from app.normalizer import normalize

    with pytest.raises(NormalizerUnavailable):
        normalize("Some description", client=FakeAnthropic(NormalizedJob()), prompt_version="v99")


def test_normalize_cost_is_null_when_usage_is_unavailable():
    """The fake test double for the SDK response carries no usage attribute
    at all, same as any response shape this app has not seen before."""
    from app.normalizer import normalize

    client = FakeAnthropic(NormalizedJob())
    result = normalize("Some description", client=client)

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.cost_usd is None


def test_board_stated_workplace_wins_over_an_inferred_one(fresh_db, monkeypatch):
    """Ashby and Lever publish workplaceType directly; a model guess must never
    override something the board actually stated."""
    from app.jobs_service import fetch_and_store

    class SourceWithWorkplace(FakeSource):
        def fetch(self, job_id):
            job = super().fetch(job_id)
            job.workplace_raw = "onsite"
            return job

    import app.jobs_service as service

    monkeypatch.setattr(
        service,
        "normalize",
        lambda *a, **k: type(
            "R",
            (),
            {
                "normalized": NormalizedJob(workplace="remote"),
                "model": "fake",
                "prompt_version": "v1",
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
            },
        )(),
    )
    fetch_and_store(["a"], source=SourceWithWorkplace(), delay_seconds=0)
    with db.session_scope() as session:
        stored = session.query(JobNormalized).one()
        assert stored.workplace == "onsite"


def test_normalize_cost_is_persisted_on_the_stored_row(fresh_db, monkeypatch):
    import app.jobs_service as service
    from app.jobs_service import fetch_and_store, total_normalize_cost
    from app.normalizer import NormalizerResult

    monkeypatch.setattr(
        service,
        "normalize",
        lambda *a, **k: NormalizerResult(
            normalized=NormalizedJob(), model="claude-haiku-4-5", prompt_version="v1",
            input_tokens=1000, output_tokens=200, cost_usd=0.002,
        ),
    )
    fetch_and_store(["a"], source=FakeSource(), delay_seconds=0)

    with db.session_scope() as session:
        stored = session.query(JobNormalized).one()
        assert (stored.input_tokens, stored.output_tokens, stored.cost_usd) == (1000, 200, 0.002)

    assert total_normalize_cost() == 0.002


def test_total_normalize_cost_treats_null_as_zero(fresh_db):
    from app.jobs_service import total_normalize_cost

    with db.session_scope() as session:
        session.add(
            Job(source="linkedin", job_id="a", title="A", company="X")
        )
        session.add(
            JobNormalized(source="linkedin", job_id="a", title="A", company="X", cost_usd=None)
        )

    assert total_normalize_cost() == 0.0


def test_total_evaluation_cost_sums_and_treats_null_as_zero(fresh_db):
    from app.evaluations_service import total_evaluation_cost

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="A", company="X"))
        session.add(Job(source="linkedin", job_id="b", title="B", company="X"))
        session.add(
            Evaluation(source="linkedin", job_id="a", rubric_version="v1", verdict="APPLY", cost_usd=0.01)
        )
        session.add(
            Evaluation(source="linkedin", job_id="b", rubric_version="v1", verdict="SKIP", cost_usd=None)
        )

    assert total_evaluation_cost() == 0.01


# ------------------------------------------------------------- env loading

def test_env_file_populates_missing_variables(tmp_path, monkeypatch):
    from app.config import _load_env_file

    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "ANTHROPIC_API_KEY=sk-test-value\n"
        'QUOTED_VALUE="with quotes"\n'
        "NOT_A_PAIR\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("QUOTED_VALUE", raising=False)

    _load_env_file(env)

    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-value"
    assert os.environ["QUOTED_VALUE"] == "with quotes"


def test_real_environment_wins_over_the_file(tmp_path, monkeypatch):
    """Exporting a key for one run must override the file, not be ignored."""
    from app.config import _load_env_file

    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")

    _load_env_file(env)

    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_missing_env_file_is_not_an_error(tmp_path):
    from app.config import _load_env_file

    _load_env_file(tmp_path / "does-not-exist")


# ------------------------------------------------------------- list views

def test_raw_listing_includes_the_whole_description(fresh_db):
    """The Raw tab exists to show what the database really holds, so the full
    text is returned rather than a preview."""
    from app.jobs_service import list_jobs

    with db.session_scope() as session:
        session.add(
            Job(
                source="linkedin",
                job_id="a",
                title="Staff PM",
                company="Example Corp",
                description_raw="x" * 4000,
                level_raw="Mid-Senior level",
            )
        )

    rows = list_jobs()
    assert len(rows) == 1
    assert len(rows[0]["description_raw"]) == 4000
    assert rows[0]["description_chars"] == 4000
    assert rows[0]["level_raw"] == "Mid-Senior level"


def test_normalized_listing_reports_which_model_produced_it(fresh_db):
    """When the prompt changes, model and normalized_at are the only way to
    tell which rows came from which version."""
    from app.jobs_service import list_normalized

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="Staff PM", company="Example Corp"))
        session.add(
            JobNormalized(
                source="linkedin",
                job_id="a",
                title="Staff PM",
                company="Example Corp",
                responsibilities=["Ship"],
                qualifications=["7 years"],
                comp_min=180000,
                comp_max=220000,
                model="claude-haiku-4-5",
            )
        )

    rows = list_normalized()
    assert len(rows) == 1
    assert rows[0]["model"] == "claude-haiku-4-5"
    assert rows[0]["responsibilities"] == ["Ship"]
    assert rows[0]["normalized_at"] is not None


def test_unstated_compensation_stays_null_in_the_listing(fresh_db):
    """Null must survive to the UI so "not stated" reads differently from zero."""
    from app.jobs_service import list_normalized

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="T", company="C"))
        session.add(JobNormalized(source="linkedin", job_id="a", title="T", company="C"))

    row = list_normalized()[0]
    assert row["comp_min"] is None
    assert row["comp_max"] is None
    assert row["workplace"] is None
    assert row["responsibilities"] == []


def test_listings_can_be_filtered_by_source(fresh_db):
    from app.jobs_service import list_jobs

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="1", title="A", company="X"))
        session.add(Job(source="greenhouse", job_id="1", title="B", company="Y"))

    assert len(list_jobs()) == 2
    assert len(list_jobs("linkedin")) == 1
    assert list_jobs("greenhouse")[0]["title"] == "B"


def test_empty_database_lists_cleanly(fresh_db):
    from app.jobs_service import list_jobs, list_normalized

    assert list_jobs() == []
    assert list_normalized() == []


def test_role_summary_must_be_copied_from_the_posting():
    """The check behind "the posting's own words": a sentence survives only if
    it appears in the description. Line breaks, case, curly quotes and dashes
    are typography, not wording; anything else is a rewrite."""
    from app.normalizer import verify_copied

    description = (
        "About the team\nThe Growth team owns\nactivation for Toast’s restaurant platform — "
        "from sign-up to first sale.\n\nWhat you'll do..."
    )
    kept, rejected = verify_copied(
        [
            "The Growth team owns activation for Toast's restaurant platform - from sign-up to first sale.",
            "The Growth team drives activation for Toast's B2B platform.",
        ],
        description,
    )
    assert kept == ["The Growth team owns activation for Toast's restaurant platform - from sign-up to first sale."]
    assert rejected == ["The Growth team drives activation for Toast's B2B platform."]


def test_normalize_drops_role_summary_sentences_not_in_the_posting():
    from app.normalizer import normalize

    client = FakeAnthropic(
        NormalizedJob(role_summary=["We build tools for restaurants.", "A sentence the model wrote itself."])
    )
    result = normalize("Intro. We build tools for restaurants. More text.", client=client)

    assert result.normalized.role_summary == ["We build tools for restaurants."]
    assert result.role_summary_rejected == ["A sentence the model wrote itself."]


def test_renormalize_rewrites_a_stored_row_from_its_raw_description(fresh_db, monkeypatch):
    """No refetch: re-normalizing reads the stored description and overwrites
    the job_normalized row, stamping the new version and role_summary."""
    import app.jobs_service as service
    from app.embeddings_service import EmbeddingUnavailable
    from app.normalizer import NormalizerResult

    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="PM", company="X", description_raw="We grow X. Own it."))
        session.add(JobNormalized(source="linkedin", job_id="a", title="PM", company="X",
                                  responsibilities=["old"], normalizer_version="v2"))

    seen = {}

    def fake_normalize(description, **kwargs):
        seen["description"] = description
        return NormalizerResult(
            normalized=NormalizedJob(responsibilities=["Own it."], role_summary=["We grow X."]),
            model="claude-haiku-4-5", prompt_version="v3", cost_usd=0.005,
        )

    monkeypatch.setattr(service, "normalize", fake_normalize)
    monkeypatch.setattr(service, "embed_normalized_job",
                        lambda *a, **k: (_ for _ in ()).throw(EmbeddingUnavailable("offline")))

    report = service.renormalize([("linkedin", "a"), ("linkedin", "missing")])

    assert seen["description"] == "We grow X. Own it."
    assert report.normalized == ["a"]
    assert report.failures == {"missing": "no stored description"}
    assert report.cost_usd == 0.005
    with db.session_scope() as session:
        row = session.get(JobNormalized, ("linkedin", "a"))
        assert row.role_summary == ["We grow X."]
        assert row.responsibilities == ["Own it."]
        assert row.normalizer_version == "v3"


def test_role_summary_is_capped_at_three_sentences():
    from app.normalizer import normalize

    sentences = [f"Sentence {i}." for i in range(1, 7)]
    client = FakeAnthropic(NormalizedJob(role_summary=sentences))
    result = normalize(" ".join(sentences), client=client)

    assert result.normalized.role_summary == sentences[:3]


def test_without_the_linkedin_module_a_linkedin_fetch_reports_it_is_not_in_this_build(fresh_db, monkeypatch):
    """The public build ships without app/linkedin_guest.py."""
    import app.jobs_service as service

    monkeypatch.setattr(service, "linkedin_fetch_available", lambda: False)
    with pytest.raises(JobDescriptionError, match="not included in this build"):
        service.fetch_and_store(["123"], delay_seconds=0)
