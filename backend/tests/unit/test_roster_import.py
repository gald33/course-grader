from pathlib import Path

from openpyxl import Workbook

from app.services.roster_import import parse_roster_xlsx


def test_parse_roster_fixture():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sample_roster.xlsx"
    rows = parse_roster_xlsx(str(fixture))
    assert len(rows) == 2
    assert rows[0].national_id == "123456789"
    assert rows[0].name == "ישראל ישראלי"
    assert rows[0].attendance_percent == 100.0


def test_parse_roster_computes_attendance_when_percentage_missing(tmp_path):
    path = tmp_path / "roster.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["תעודת זהות", "שם", "נוכחות מפגש 1", "נוכחות מפגש 2", "נוכחות מפגש 3"])
    ws.append(["123456789", "ישראל ישראלי", 1, 0, 1])
    wb.save(path)

    rows = parse_roster_xlsx(str(path))
    assert len(rows) == 1
    assert rows[0].attendance_percent == 66.67
