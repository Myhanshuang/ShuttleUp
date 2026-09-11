from pathlib import Path

from shuttleup.availability.wakeup import WakeUpImporter, expand_occurrences


def test_normalize_odd_even_weeks_and_period_gaps():
    payload = (Path(__file__).parent / "fixtures/wakeup-normalized.json").read_bytes()
    schedule = WakeUpImporter().normalize(payload); occurrences = expand_occurrences(schedule)
    odd = [o for o in occurrences if o["starts_at"].startswith(("2026-09-09", "2026-09-23"))]
    assert len(odd) == 4
    assert odd[0]["ends_at"].endswith("08:45:00+08:00")
    assert odd[1]["starts_at"].endswith("08:55:00+08:00")
    assert any(o["starts_at"].startswith("2026-09-18") for o in occurrences)
    assert any(o["starts_at"].startswith("2026-09-26") for o in occurrences)

