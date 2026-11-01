interface ValidationResult {
  ok: boolean;
  rows: number;
  latestUpdated: string | null;
  reason: string | null;
}

const REQUIRED_HEADERS = [
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
] as const;

function main(workbook: ExcelScript.Workbook, minRows: number): ValidationResult {
  const worksheets = workbook.getWorksheets();
  if (worksheets.length === 0) {
    return { ok: false, rows: 0, latestUpdated: null, reason: "No worksheet found" };
  }

  const sheet = worksheets[0];
  const values = sheet.getUsedRangeOrNullObject();
  if (!values || values.isNullObject) {
    return { ok: false, rows: 0, latestUpdated: null, reason: "Workbook has no data" };
  }

  const matrix = values.getValues() as Array<Array<string | number | boolean>>;
  if (matrix.length < 2) {
    return { ok: false, rows: 0, latestUpdated: null, reason: "Workbook contains no data rows" };
  }

  const headers = matrix[0].map((value) => String(value ?? "").trim());
  const missing = REQUIRED_HEADERS.filter((header) => !headers.includes(header));
  if (missing.length > 0) {
    return {
      ok: false,
      rows: Math.max(0, matrix.length - 1),
      latestUpdated: null,
      reason: `Missing required headers: ${missing.join(", ")}`,
    };
  }

  const normalizedRows = matrix.slice(1).filter((row) =>
    row.some((value) => value !== null && value !== undefined && String(value).trim() !== "")
  );
  if (!Number.isFinite(minRows) || minRows < 0) {
    return { ok: false, rows: normalizedRows.length, latestUpdated: null, reason: "MIN_ROWS must be zero or greater" };
  }
  if (normalizedRows.length < minRows) {
    return {
      ok: false,
      rows: normalizedRows.length,
      latestUpdated: null,
      reason: `Row count below MIN_ROWS`,
    };
  }

  const numberIndex = headers.indexOf("Number");
  const openedIndex = headers.indexOf("Opened");
  const updatedIndex = headers.indexOf("Updated");
  if (normalizedRows.some((row) =>
    String(row[numberIndex] ?? "").trim() === "" &&
    String(row[openedIndex] ?? "").trim() === "" &&
    String(row[updatedIndex] ?? "").trim() === ""
  )) {
    return {
      ok: false,
      rows: normalizedRows.length,
      latestUpdated: null,
      reason: "Fully blank key columns found",
    };
  }

  let latestUpdated: string | null = null;
  for (const row of normalizedRows) {
    const raw = row[updatedIndex];
    if (typeof raw === "number") {
      const serial = raw;
      const millis = Math.round((serial - 25569) * 86400 * 1000);
      const value = new Date(millis).toISOString();
      if (!latestUpdated || value > latestUpdated) latestUpdated = value;
    } else if (typeof raw === "string" && raw.trim() !== "") {
      const parsed = new Date(raw);
      if (!Number.isNaN(parsed.getTime())) {
        const value = parsed.toISOString();
        if (!latestUpdated || value > latestUpdated) latestUpdated = value;
      }
    }
  }

  if (!latestUpdated) {
    return { ok: false, rows: normalizedRows.length, latestUpdated: null, reason: "Updated column contains no valid date" };
  }

  return { ok: true, rows: normalizedRows.length, latestUpdated, reason: null };
}
