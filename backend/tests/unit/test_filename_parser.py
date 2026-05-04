from app.services.filename_parser import parse_filename


def test_parse_submission_filename():
    parsed = parse_filename("ID_123456789+ID_987654321_WorkCode_2.pdf")
    assert parsed.ids == ["123456789", "987654321"]
    assert parsed.workcode == 2
    assert parsed.originality_score is None
    assert parsed.is_originality_pdf is False


def test_parse_originality_filename():
    parsed = parse_filename("ID_111111111_WorkCode_2_OriginalityReturn_14.3.PDF")
    assert parsed.ids == ["111111111"]
    assert parsed.workcode == 2
    assert parsed.originality_score == 14.3
    assert parsed.is_originality_pdf is True
