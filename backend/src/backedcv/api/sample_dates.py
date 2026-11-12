"""The built-in samples keep the day their pinned answers were recorded.

What the model reads includes the CV's total experience, which counts the months up to the
analysis date. Analysed on its pinned day, a sample gives the model the exact input of the pinned
run in any month, so its answers stay pinned and its report never changes."""

import hashlib
import json
import logging
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from backedcv.domain.models import CVLine
from backedcv.domain.text import normalize_text
from backedcv.ingestion import IngestionError, read_cv, read_cv_text
from backedcv.llm.cache import PINNED_FILE
from backedcv.settings import get_settings

log = logging.getLogger(__name__)

# Set by scripts/pin_samples.py while it records, so the new answers are pinned to the day of
# the recording and not to the day of the file they replace.
recording_date: date | None = None


def fingerprint(job_text: str, lines: list[CVLine]) -> str:
    """One hash of a posting and the CV lines read for it, both in their canonical form."""
    parts = [normalize_text(job_text), *(line.text for line in lines)]
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def sample_date(job_text: str, lines: list[CVLine]) -> date | None:
    """The pinned day when this posting and CV are one of the built-in samples, else None."""
    folder = get_settings().samples_dir
    pinned_on = recording_date or _pinned_on(folder)
    if pinned_on is None or fingerprint(job_text, lines) not in _sample_fingerprints(folder):
        return None
    return pinned_on


@lru_cache(maxsize=4)
def _pinned_on(folder: Path) -> date | None:
    """The day the pinned answers were recorded (`generated_at` in the pinned file)."""
    try:
        payload = json.loads((folder / PINNED_FILE).read_text(encoding="utf-8"))
        return datetime.fromisoformat(payload["generated_at"]).date()
    except (OSError, ValueError, KeyError, TypeError):
        return None


@lru_cache(maxsize=4)
def _sample_fingerprints(folder: Path) -> frozenset[str]:
    """The samples as the UI sends them: the curated CV as its PDF, the hidden-risk CV as text."""
    readers = (
        ("curated", lambda d: read_cv((d / "cv.pdf").read_bytes(), "sample-cv.pdf")),
        ("hidden_risk", lambda d: read_cv_text((d / "cv.txt").read_text(encoding="utf-8"))),
    )
    found = set()
    for name, read in readers:
        try:
            job_text = (folder / name / "job.txt").read_text(encoding="utf-8")
            found.add(fingerprint(job_text, read(folder / name).lines))
        except (OSError, IngestionError) as exc:
            log.warning("Sample %s has no pinned day: %s", name, exc)
    return frozenset(found)
