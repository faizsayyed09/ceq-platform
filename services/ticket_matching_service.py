from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol

from .fingerprint_service import FingerprintResult


class MatchStatus(str):
    pass


MATCHED = "MATCHED"
AMBIGUOUS = "AMBIGUOUS"
NOT_FOUND = "NOT_FOUND"
PENDING_EXPORT = "PENDING_EXPORT"
NO_EXPORT = "NO_EXPORT"


@dataclass(frozen=True)
class TicketRow:
    values: Mapping[str, Any]


@dataclass(frozen=True)
class TicketExportResult:
    rows: tuple[TicketRow, ...] = ()
    label: str = ""
    uploaded_at: datetime | None = None
    newest_activity_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True)
class TicketFacts:
    opened_by_agent: bool = False
    opened_in_window: bool = False
    agent_touched_in_window: bool = False
    caller_name_in_ticket: bool = False
    caller_phone_in_ticket: bool | None = None
    contact_type_matches_channel: bool = False
    kb_articles_in_ticket: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchCandidate:
    number: str
    score: int
    reasons: tuple[str, ...]
    opened_et: str
    row: TicketRow
    facts: TicketFacts


@dataclass(frozen=True)
class PrematchResult:
    status: str
    confidence: str
    best_ticket: str
    candidates: tuple[MatchCandidate, ...]
    candidate_rows: Mapping[str, Mapping[str, Any]]
    export_rows: int
    export_label: str = ""
    export_error: str | None = None


class TicketExportProvider(Protocol):
    def get_latest_export(self) -> TicketExportResult:
        ...


class TicketMatchingService:
    XNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    NOTE_RE = re.compile(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}) - ([^\n(]+?) \((?:Work notes|Additional comments)\)")
    KB_RE = re.compile(r"\bKB\d{6,}\b", re.IGNORECASE)
    NUMLIKE_RE = re.compile(r"\+?\d[\d \t.\-]{3,}\d|\d{5,}")
    ROW_FORMATS = ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M")
    STOP = {"that", "this", "with", "have", "from", "your", "there", "their", "they", "them", "then", "than", "what", "when", "where", "which", "while", "would", "could", "should", "about", "after", "again", "also", "been", "before", "being", "both", "come", "does", "doing", "done", "down", "each", "even", "ever", "every", "here", "into", "just", "know", "like", "make", "many", "more", "most", "much", "must", "need", "okay", "other", "over", "please", "really", "right", "same", "some", "still", "sure", "take", "tell", "thank", "thanks", "these", "thing", "things", "think", "those", "through", "today", "told", "very", "want", "wanted", "well", "were", "will", "yeah", "yours", "call", "calling", "called", "help", "number", "ticket", "name", "hello", "good", "morning", "evening", "afternoon", "able", "sorry", "welcome", "anything", "else", "issue", "problem", "working", "work", "time", "mean", "actually", "because", "something", "going", "check", "give", "minute", "hold", "back", "line", "service", "desk", "direct", "extension"}

    def match(self, fingerprint: FingerprintResult, export: TicketExportResult | None = None, tickets: list[Mapping[str, Any]] | None = None, *, top_candidates: int = 3, window_minutes: int = 60, pending_grace_minutes: int = 60) -> PrematchResult:
        if export is None:
            export = TicketExportResult(rows=tuple(TicketRow(row) for row in (tickets or [])))
        elif tickets:
            rows = export.rows + tuple(TicketRow(row) for row in tickets)
            export = TicketExportResult(rows=rows, label=export.label, uploaded_at=export.uploaded_at, newest_activity_at=export.newest_activity_at, error=export.error)

        rows = export.rows
        ids = fingerprint.identifiers
        lo = fingerprint.search_window_start
        hi = fingerprint.search_window_end
        if lo is None and ids.ticket_numbers:
            lo, hi = datetime(1900, 1, 1), datetime(2100, 1, 1)

        document_frequency: dict[str, int] = {}
        for ticket_row in rows:
            row = ticket_row.values
            for word in self._words(self._get(row, "Short description") + " " + self._get(row, "Description")):
                document_frequency[word] = document_frequency.get(word, 0) + 1
        df_cap = max(3, len(rows) // 10)

        issue_words = self._words(fingerprint.issue_excerpt)
        context = {
            "lo": lo, "hi": hi, "start": fingerprint.interaction.started_at,
            "end": fingerprint.interaction.ended_at, "channel": fingerprint.interaction.channel,
            "emails": set(fingerprint.interaction.agent_emails), "names": list(fingerprint.interaction.agent_names),
            "tickets": ids.ticket_numbers, "name_tokens": ids.name_tokens, "numbers": ids.caller_numbers,
            "phones": ids.caller_phones, "ids": ids.identifiers, "issue_words": issue_words,
            "df": document_frequency, "df_cap": df_cap,
        }
        scored = [candidate for candidate in (self._score(row.values, context) for row in rows) if candidate is not None]
        scored.sort(key=lambda candidate: (-candidate.score, candidate.number))
        top = tuple(scored[:max(1, top_candidates)])

        if not rows:
            status, confidence = NO_EXPORT, "LOW"
        elif not top or top[0].score < 45:
            status, confidence = NOT_FOUND, "LOW"
            reference = export.uploaded_at or export.newest_activity_at
            grace = timedelta(minutes=pending_grace_minutes)
            if fingerprint.interaction.ended_at and reference and reference < fingerprint.interaction.ended_at + grace:
                status = PENDING_EXPORT
        else:
            best = top[0].score
            second = top[1].score if len(top) > 1 else 0
            if best >= 100 or (best >= 70 and best - second >= 25):
                status, confidence = MATCHED, "HIGH"
            else:
                status, confidence = AMBIGUOUS, "MEDIUM"

        best_ticket = top[0].number if top and status in (MATCHED, AMBIGUOUS) else ""
        candidate_rows = {candidate.number: dict(candidate.row.values) for candidate in top}
        return PrematchResult(status=status, confidence=confidence, best_ticket=best_ticket, candidates=top, candidate_rows=candidate_rows, export_rows=len(rows), export_label=export.label, export_error=export.error)

    def parse_xlsx(self, data: bytes) -> list[TicketRow]:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for node in root.iter(self.XNS + "si"):
                shared.append("".join(text.text or "" for text in node.iter(self.XNS + "t")))
        sheets = sorted(name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        if not sheets:
            return []
        table: list[list[str]] = []
        for row_node in ET.fromstring(zf.read(sheets[0])).iter(self.XNS + "row"):
            cells: dict[int, str] = {}
            for cell in row_node.iter(self.XNS + "c"):
                reference = cell.get("r", "")
                index = 0
                for char in reference:
                    if char.isalpha():
                        index = index * 26 + ord(char.upper()) - 64
                    else:
                        break
                index -= 1
                kind = cell.get("t")
                if kind == "inlineStr":
                    value = "".join(text.text or "" for text in cell.iter(self.XNS + "t"))
                else:
                    value_node = cell.find(self.XNS + "v")
                    value = value_node.text if value_node is not None and value_node.text is not None else ""
                    if kind == "s" and value != "":
                        value = shared[int(value)]
                if index >= 0:
                    cells[index] = value
            if cells:
                table.append([cells.get(index, "") for index in range(max(cells) + 1)])
        if not table:
            return []
        headers = [str(value).strip() for value in table[0]]
        rows = []
        for values in table[1:]:
            row = {headers[index]: values[index] if index < len(values) else "" for index in range(len(headers)) if headers[index]}
            for key, value in list(row.items()):
                if key.lower().startswith(("opened", "updated")) and "by" not in key.lower():
                    parsed = self._row_dt(str(value))
                    if parsed:
                        row[key] = parsed.strftime("%Y-%m-%d %H:%M:%S")
            rows.append(TicketRow(row))
        return rows

    @staticmethod
    def _get(row: Mapping[str, Any], *keys: str) -> str:
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        for key in keys:
            value = lowered.get(key.lower())
            if value not in (None, ""):
                return str(value)
        return ""

    @staticmethod
    def _alnum(value: object) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    @staticmethod
    def _digits(value: object) -> str:
        return re.sub(r"\D", "", str(value or ""))

    def _words(self, value: object) -> set[str]:
        out: set[str] = set()
        for word in re.findall(r"[a-z]{4,}", str(value or "").lower(), re.I):
            if word in self.STOP:
                continue
            if len(word) > 5 and word.endswith("s"):
                word = word[:-1]
            out.add(word)
        return out

    def _tokens(self, value: object) -> list[str]:
        return [token for token in re.findall(r"[a-z]{3,}", str(value or "").lower()) if token not in self.STOP]

    def _similar(self, left: str, right: str) -> bool:
        return left == right or (min(len(left), len(right)) >= 4 and SequenceMatcher(None, left, right).ratio() >= 0.8)

    def _name_like(self, value: object, names: tuple[str, ...] | list[str]) -> bool:
        value_tokens = self._tokens(value)
        for name in names:
            name_tokens = self._tokens(name)
            if name_tokens and value_tokens and self._similar(name_tokens[-1], value_tokens[-1]):
                return True
        return False

    def _row_dt(self, value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            serial = float(text)
            if 20000 < serial < 80000:
                return datetime(1899, 12, 30) + timedelta(seconds=round(serial * 86400))
        except ValueError:
            pass
        for fmt in self.ROW_FORMATS:
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        return None

    def _persons(self, row: Mapping[str, Any]) -> str:
        values: list[str] = []
        for key, value in row.items():
            lowered = str(key).lower()
            if value and ("requestor" in lowered or "requested for" in lowered or lowered.startswith("contact [") or lowered in ("contact", "caller")):
                values.append(str(value))
        return " ".join(values)

    def _row_numbers(self, text: object) -> set[str]:
        output: set[str] = set()
        for match in self.NUMLIKE_RE.findall(str(text or "")):
            digits = self._digits(match)
            if len(digits) >= 5:
                output.add(digits)
            if len(digits) >= 7:
                output.add(digits[-7:])
        return output

    def _score(self, row: Mapping[str, Any], context: Mapping[str, Any]) -> MatchCandidate | None:
        number = self._get(row, "Number").strip().upper()
        if not number:
            return None
        text = " ".join(str(value) for value in row.values() if value)
        alnum = self._alnum(text)
        notes = self._get(row, "Work notes") + "\n" + self._get(row, "Additional comments")
        lo, hi = context["lo"], context["hi"]

        email = self._get(row, "Email", "Opened by.Email").strip().lower()
        by_agent = email in context["emails"] or self._name_like(self._get(row, "Opened by"), context["names"])
        opened = self._row_dt(self._get(row, "Opened"))
        updated = self._row_dt(self._get(row, "Updated", "Updated(u_updated_on)"))
        in_window = bool(opened and lo <= opened <= hi) if lo is not None and hi is not None else False

        touched = False
        if lo is not None and hi is not None:
            for timestamp, who in self.NOTE_RE.findall(notes):
                note_time = self._row_dt(timestamp)
                if note_time and lo <= note_time <= hi and self._name_like(who, context["names"]):
                    touched = True
                    break
            if not touched and updated and lo <= updated <= hi:
                if self._name_like(self._get(row, "Updated by", "Updated by(u_updated_by)"), context["names"]):
                    touched = True

        parent = self._get(row, "Parent").strip().upper()
        explicit = [ticket for ticket in context["tickets"] if ticket == number or ticket == parent or (ticket.startswith("CS") and ticket in alnum)]
        if not (by_agent or touched or explicit):
            return None

        score = 0
        reasons: list[str] = []
        if explicit:
            score += 100
            reasons.append("number from the interaction links to this row: " + ", ".join(explicit))
        if by_agent and in_window:
            score += 30
            reasons.append("opened by the agent at " + self._fmt(opened) + " ET, inside the window")
            if context["start"] and context["end"] and context["start"] - timedelta(minutes=5) <= opened <= context["end"] + timedelta(minutes=45):
                score += 10
        elif touched:
            score += 20
            reasons.append("agent noted/updated this ticket inside the window")
        elif by_agent:
            reasons.append("opened by the agent but OUTSIDE the window (" + self._fmt(opened) + " ET)")

        persons = self._tokens(self._persons(row))
        name_hits = [name for name in context["name_tokens"] if any(self._similar(name, person) for person in persons)]
        if name_hits:
            score += min(25, 10 * len(name_hits))
            reasons.append("caller name matches requester/contact (" + ", ".join(name_hits) + ")")
        else:
            description_tokens = self._tokens(self._get(row, "Description"))
            name_hits = [name for name in context["name_tokens"] if len(name) >= 4 and any(self._similar(name, description) for description in description_tokens)]
            if name_hits:
                score += min(15, 6 * len(name_hits))
                reasons.append("caller name found in description (" + ", ".join(name_hits) + ")")

        row_numbers = self._row_numbers(text)
        number_hits = [number for number in context["numbers"] if number in row_numbers or (len(number) >= 7 and number[-7:] in row_numbers)]
        if number_hits:
            score += min(35, 25 + 5 * (len(number_hits) - 1))
            reasons.append("caller numbers found in ticket (" + ", ".join(number_hits) + ")")

        id_hits = [identifier for identifier in context["ids"] if len(identifier) >= 6 and identifier in alnum]
        if id_hits:
            score += min(30, 15 * len(id_hits))
            reasons.append("IDs/assets found in ticket (" + ", ".join(id_hits) + ")")

        row_words = self._words(self._get(row, "Short description") + " " + self._get(row, "Description"))
        common = sorted(word for word in context["issue_words"] if word in row_words and context["df"].get(word, 0) <= context["df_cap"])
        if common:
            score += min(20, 5 * len(common))
            reasons.append("issue words: " + ", ".join(common[:6]))

        contact_type = self._get(row, "Contact type").lower()
        channel_hit = "phone" in contact_type if context["channel"] == "CALL" else "email" in contact_type
        if channel_hit:
            score += 5

        phone_hits = [number for number in number_hits if len(number) >= 7]
        facts = TicketFacts(opened_by_agent=by_agent, opened_in_window=in_window, agent_touched_in_window=touched, caller_name_in_ticket=bool(name_hits), caller_phone_in_ticket=(bool(phone_hits) if context["phones"] else None), contact_type_matches_channel=channel_hit, kb_articles_in_ticket=tuple(sorted({value.upper() for value in self.KB_RE.findall(notes)})))
        return MatchCandidate(number=number, score=score, reasons=tuple(reasons), opened_et=self._fmt(opened), row=TicketRow(row), facts=facts)

    @staticmethod
    def _fmt(value: datetime | None) -> str:
        return value.strftime("%Y-%m-%d %H:%M") if value else "unknown"
