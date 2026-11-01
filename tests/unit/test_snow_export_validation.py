from scripts.validate_snow_export import validate_rows


HEADERS = [
    "Number", "Opened", "Updated", "Opened by", "Email", "Company",
    "Contact", "Parent", "State", "Description", "KA number",
]


def valid_row(number="INC001"):
    return [
        number, "2026-10-01T00:00:00+00:00", "2026-10-31T12:00:00+00:00",
        "Worker", "worker@example.com", "Example Co", "Caller", "", "Active",
        "Password reset", "KB001",
    ]


def test_accepts_valid_export():
    result = validate_rows([HEADERS, valid_row()], min_rows=1)
    assert result["ok"] is True
    assert result["rows"] == 1
    assert result["latest_updated"] == "2026-10-31T12:00:00+00:00"


def test_rejects_missing_header():
    result = validate_rows([HEADERS[:-1], valid_row()[:-1]], min_rows=1)
    assert result["ok"] is False
    assert result["reason"].startswith("Missing required headers")


def test_rejects_row_below_minimum():
    result = validate_rows([HEADERS], min_rows=1)
    assert result["ok"] is False
    assert result["reason"] == "Row count below MIN_ROWS"


def test_rejects_negative_minimum():
    result = validate_rows([HEADERS, valid_row()], min_rows=-1)
    assert result["ok"] is False
    assert result["reason"] == "MIN_ROWS must be zero or greater"


def test_rejects_fully_blank_key_columns():
    row = valid_row()
    row[0] = ""
    row[1] = ""
    row[2] = ""
    result = validate_rows([HEADERS, row], min_rows=1)
    assert result["ok"] is False
    assert result["reason"] == "Fully blank key columns found"


def test_rejects_missing_valid_updated_date():
    row = valid_row()
    row[2] = "not-a-date"
    result = validate_rows([HEADERS, row], min_rows=1)
    assert result["ok"] is False
    assert result["reason"] == "Updated column contains no valid date"
