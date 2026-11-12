"""The built-in samples are analysed as of the day their answers were pinned."""

import json
from datetime import date

from backedcv.api import sample_dates
from backedcv.api.sample_dates import sample_date
from backedcv.graph.recompute import today_of
from backedcv.ingestion import read_cv, read_cv_text
from backedcv.settings import get_settings

SAMPLES = get_settings().samples_dir
HIDDEN_JOB = (SAMPLES / "hidden_risk" / "job.txt").read_text(encoding="utf-8")
HIDDEN_CV = read_cv_text((SAMPLES / "hidden_risk" / "cv.txt").read_text(encoding="utf-8")).lines


def _pinned_day() -> date:
    payload = json.loads((SAMPLES / "pinned_answers.json").read_text(encoding="utf-8"))
    return date.fromisoformat(payload["generated_at"][:10])


def test_both_built_in_samples_get_the_pinned_day():
    curated = read_cv((SAMPLES / "curated" / "cv.pdf").read_bytes(), "any-name.pdf")
    curated_job = (SAMPLES / "curated" / "job.txt").read_text(encoding="utf-8")

    assert sample_date(curated_job, curated.lines) == _pinned_day()
    assert sample_date(HIDDEN_JOB, HIDDEN_CV) == _pinned_day()


def test_blank_space_around_the_posting_does_not_matter():
    assert sample_date("\n\n" + HIDDEN_JOB + "  \n", HIDDEN_CV) == _pinned_day()


def test_any_other_input_has_no_pinned_day():
    other_cv = read_cv_text("Jane Doe\nData Engineer").lines

    assert sample_date(HIDDEN_JOB + "\nOne more line.", HIDDEN_CV) is None
    assert sample_date(HIDDEN_JOB, other_cv) is None


def test_a_recording_run_pins_the_samples_to_its_own_day(monkeypatch):
    monkeypatch.setattr(sample_dates, "recording_date", date(2030, 1, 2))

    assert sample_date(HIDDEN_JOB, HIDDEN_CV) == date(2030, 1, 2)


def test_the_analysis_date_prefers_as_of():
    created = "2027-03-01T10:00:00+00:00"

    assert today_of({"as_of": "2026-10-23", "created_at": created}) == date(2026, 10, 23)
    assert today_of({"created_at": created}) == date(2027, 3, 1)
