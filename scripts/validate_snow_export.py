from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable


REQUIRED_HEADERS = (
    "Number",
    "Opened",
    "Updated",
    "Opened by",
    "Email",
    "Company",
    "Contact",
    "Parent",
    "State",
    "Description",
    "KA number",
)


def validate_rows(rows: Iterable[Iterable[object]], min_rows: int) -> dict[str, object]:
    materialized = [[("" if value is None else str(value).strip()) for value in row] for row in rows]
    if not materialized:
        return {"ok": False, "rows": 0, "latest_updated": None, "reason": "Workbook has no data"}

    headers = [value.strip() for value in materialized[0]]
    missing = [header for header in REQUIRED_HEADERS if header not in headers]
    if missing:
        return {
            "ok": False,
            "rows": max(0, len(materialized) - 1),
            "latest_updated": None,
            "reason": f"Missing required headers: {', '.join(missing)}",
        }

    if min_rows < 0:
        return {"ok": False, "rows": len(materialized) - 1, "latest_updated": None, "reason": "MIN_ROWS must be zero or greater"}

    data_rows = [row for row in materialized[1:] if any(row)]
    if len(data_rows) < min_rows:
        return {"ok": False, "rows": len(data_rows), "latest_updated": None, "reason": "Row count below MIN_ROWS"}

    number_index = headers.index("Number")
    opened_index = headers.index("Opened")
    updated_index = headers.index("Updated")
    data_rows = [
        row + [""] * max(0, len(headers) - len(row))
        for row in data_rows
    ]
    if any(
        not row[number_index] and not row[opened_index] and not row[updated_index]
        for row in data_rows
    ):
        return {
            "ok": False,
            "rows": len(data_rows),
            "latest_updated": None,
            "reason": "Fully blank key columns found",
        }

    latest_updated: str | None = None
    for row in data_rows:
        if len(row) <= updated_index or not row[updated_index]:
            continue
        for candidate in (row[updated_index], row[updated_index].replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                iso_value = parsed.isoformat()
                if latest_updated is None or iso_value > latest_updated:
                    latest_updated = iso_value
                break
            except ValueError:
                continue

    if latest_updated is None:
        return {
            "ok": False,
            "rows": len(data_rows),
            "latest_updated": None,
            "reason": "Updated column contains no valid date",
        }

    return {"ok": True, "rows": len(data_rows), "latest_updated": latest_updated, "reason": None}


def validate_csv(path: str | Path, min_rows: int) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return validate_rows(rows, min_rows)
