from pathlib import Path

from app.services.presentation_import import aggregate_presentation_rows, parse_presentations_xlsx


def test_parse_presentation_fixture():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sample_presentations.xlsx"
    rows = aggregate_presentation_rows(parse_presentations_xlsx(str(fixture)))

    initial_rows = [r for r in rows if r.stage == "initial"]
    final_rows = [r for r in rows if r.stage == "final"]

    assert len(initial_rows) >= 2
    assert len(final_rows) >= 2
    student = next(x for x in initial_rows if x.national_id == "123456789")
    assert round(student.clarity or 0, 2) == 4.5
