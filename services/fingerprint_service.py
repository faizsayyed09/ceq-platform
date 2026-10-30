from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FingerprintStatus(str):
    pass


@dataclass(frozen=True)
class InteractionContext:
    channel: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    clean_transcript: str
    agent_names: tuple[str, ...] = ()
    agent_emails: tuple[str, ...] = ()


@dataclass(frozen=True)
class FingerprintIdentifiers:
    ticket_numbers: tuple[str, ...] = ()
    caller_numbers: tuple[str, ...] = ()
    caller_phones: tuple[str, ...] = ()
    caller_emails: tuple[str, ...] = ()
    caller_names: tuple[str, ...] = ()
    caller_names_heard: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    name_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class FingerprintResult:
    fingerprint_text: str
    interaction: InteractionContext
    identifiers: FingerprintIdentifiers
    issue_excerpt: str = ""
    location_statements: tuple[str, ...] = ()
    caller_requested_pauses: tuple[dict[str, object], ...] = ()
    search_window_start: datetime | None = None
    search_window_end: datetime | None = None


class FingerprintService:
    TICKET_RE = re.compile(r"\b(?:INC|RITM|REQ|TASK|CHG|PRB|CS)\s?\d{6,}\b", re.IGNORECASE)
    LINE_RE = re.compile(r"^\[(\d{1,3}):(\d{2})\]\s+(AGENT|CALLER|IVR):\s*(.*)$")
    EMAIL_RE = re.compile(r"[\w.\-]+@[\w\-]+(?:\.[\w\-]+)+")
    PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d \t().-]{5,}\d(?![\w-])")
    DIGITS_RE = re.compile(r"(?<!\d)\d{5,15}(?!\d)")
    ID_RE = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,}\b")
    NAME_RE = re.compile(r"(?i:\bmy name is|\bmy name's|\bfull name is|\bthis is)\s+([A-Z][A-Za-z'\-]+(?:[ ,]+[A-Z][A-Za-z'\-]+){0,3})")
    ADDRESS_RE = re.compile(r"(?i:\b(?:thank you|thanks|okay|alright|sure|and|hi|hello))[,]?\s+([A-Z][a-z]{2,})\b")
    HELP_RE = re.compile(r"how (?:may|can|could) i (?:help|assist)|what can i (?:do|help)|can i help", re.IGNORECASE)
    HOLD_RE = re.compile(r"hold on|can you hold|give me (?:a|one|two|1|2) (?:sec|second|minute|min|moment)|one (?:sec|second|moment|minute)|bear with me|let me (?:check|get|find|grab|look)", re.IGNORECASE)
    LOCATION_RE = re.compile(r"\b(?:department|dept|unit|building|floor|room|clinic|ward|campus|station|office|site)\b", re.IGNORECASE)

    STOP = {"that", "this", "with", "have", "from", "your", "there", "their", "they", "them", "then", "than", "what", "when", "where", "which", "while", "would", "could", "should", "about", "after", "also", "been", "before", "being", "both", "does", "doing", "done", "down", "each", "even", "ever", "every", "here", "into", "just", "know", "like", "make", "many", "more", "most", "much", "must", "need", "other", "over", "please", "really", "right", "same", "some", "still", "sure", "take", "tell", "thank", "thanks", "these", "thing", "things", "think", "those", "through", "today", "told", "very", "want", "wanted", "well", "were", "will", "yeah", "yours", "call", "calling", "called", "help", "number", "ticket", "name", "hello", "good", "morning", "evening", "afternoon", "able", "sorry", "welcome", "anything", "else", "issue", "problem", "working", "work", "time", "mean", "actually", "because", "something", "going", "check", "give", "minute", "hold", "back", "line", "service", "desk", "direct", "extension"}
    NOT_NAMES = {"Thank", "Thanks", "Please", "Sure", "Okay", "Yes", "Yeah", "You", "Your", "The", "This", "That", "What", "Can", "May", "Let", "Have", "Bye", "Just", "Now", "Good", "Great", "Perfect", "Alright", "Hello", "One", "Give", "Got", "Sir", "Madam", "Maam", "Take", "Right", "Well", "Hold", "Welcome"}

    @staticmethod
    def _utc(value: datetime | str | None) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @classmethod
    def _to_eastern(cls, dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        try:
            return dt.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
        except (ZoneInfoNotFoundError, ValueError, OverflowError):
            u = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return u - timedelta(hours=4 if 3 <= u.month <= 10 else 5)

    @staticmethod
    def _unique(items: Iterable[str], limit: int = 8) -> tuple[str, ...]:
        out: list[str] = []
        for item in items:
            if item and item not in out:
                out.append(item)
            if len(out) >= limit:
                break
        return tuple(out)

    @staticmethod
    def _digits(value: object) -> str:
        return re.sub(r"\D", "", str(value or ""))

    @staticmethod
    def _tokens(value: object) -> tuple[str, ...]:
        return tuple(t for t in re.findall(r"[a-z]{3,}", str(value or "").lower()) if t not in FingerprintService.STOP)

    def fingerprint(self, transcript: str = "", *, status: str = "DONE", channel: str = "CALL", call_start: datetime | str | None = None, call_end: datetime | str | None = None, agent_names: Iterable[str] = (), agent_emails: Iterable[str] = (), long_silence_events: Iterable[Mapping[str, object]] = (), window_minutes: int = 60, turn_chars: int = 200) -> FingerprintResult:
        agent_names_tuple = tuple(str(v).strip() for v in agent_names if str(v).strip())
        agent_emails_tuple = tuple(str(v).strip().lower() for v in agent_emails if str(v).strip())
        channel = "EMAIL" if "EMAIL" in str(channel).upper() else "CALL"
        start = self._utc(call_start)
        end = self._utc(call_end) or start
        s_et = self._to_eastern(start)
        e_et = self._to_eastern(end)
        lo = s_et - timedelta(minutes=window_minutes) if s_et else None
        hi = e_et + timedelta(minutes=window_minutes) if e_et else None

        clean = str(transcript or "").replace("(?)", "")
        lines: list[tuple[str, int, str]] = []
        for raw in clean.splitlines():
            match = self.LINE_RE.match(raw.strip())
            if match:
                lines.append((match.group(3).upper(), int(match.group(1)) * 60 + int(match.group(2)), match.group(4)))
        if not lines and clean.strip():
            lines = [("CALLER", 0, clean)]
        spoken = tuple(line for line in lines if line[0] != "IVR")
        caller = " ".join(text for speaker, _, text in lines if speaker == "CALLER")
        agent = " ".join(text for speaker, _, text in lines if speaker == "AGENT")
        spoken_text = " ".join(text for _, _, text in spoken)

        tickets = self._unique([re.sub(r"\s", "", value).upper() for value in self.TICKET_RE.findall(spoken_text)], 8)
        ticket_digits = {self._digits(value) for value in tickets}
        numbers = [self._digits(match) for match in self.PHONE_RE.findall(spoken_text)]
        numbers += self.DIGITS_RE.findall(spoken_text)
        numbers = self._unique([value for value in numbers if 5 <= len(value) <= 15 and value not in ticket_digits], 8)
        identifiers = self._unique([re.sub(r"[^A-Z0-9]", "", match).upper() for match in self.ID_RE.findall(spoken_text) if not self.TICKET_RE.match(match)], 8)
        emails = self._unique([value.lower() for value in self.EMAIL_RE.findall(spoken_text.replace(" .", "."))], 3)
        names = self._unique([value.strip(" ,") for value in self.NAME_RE.findall(caller)], 3)
        own_tokens = {token for name in agent_names_tuple for token in self._tokens(name)}
        heard: list[str] = []
        for value in self.ADDRESS_RE.findall(agent):
            if value not in self.NOT_NAMES and value.lower() not in own_tokens:
                heard.append(value)
        heard_names = self._unique(heard, 3)

        starts = [index + 1 for index, (speaker, _, text) in enumerate(spoken) if speaker == "AGENT" and self.HELP_RE.search(text)]
        issue_start = starts[0] if starts else min(3, len(spoken))
        issue = spoken[issue_start:issue_start + 10]
        issue_text = " ".join(text for _, _, text in issue)
        issue_excerpt = self._clip(" ".join(text for speaker, _, text in issue if speaker == "CALLER"), 600)
        locations = self._unique([text.strip() for speaker, _, text in spoken if speaker == "CALLER" and self.LOCATION_RE.search(text)], 4)

        pauses: list[dict[str, object]] = []
        caller_lines = [(seconds, text) for speaker, seconds, text in spoken if speaker == "CALLER"]
        for event in long_silence_events:
            try:
                silence_start = float(event.get("start", 0))
                duration = float(event.get("duration", 0) or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            asks = [(seconds, text) for seconds, text in caller_lines if 0 <= silence_start - seconds <= 25 and self.HOLD_RE.search(text)]
            if asks:
                seconds, text = asks[-1]
                pauses.append({"silence_start": self._mmss(silence_start), "silence_sec": int(round(duration)), "requested_at": self._mmss(seconds), "caller_said": self._clip(text, 100)})

        ids = FingerprintIdentifiers(
            ticket_numbers=tickets,
            caller_numbers=numbers,
            caller_phones=tuple(number for number in numbers if len(number) >= 7),
            caller_emails=emails,
            caller_names=names,
            caller_names_heard=heard_names,
            identifiers=identifiers,
            name_tokens=self._unique([token for name in names + heard_names for token in self._tokens(name)], 8),
        )
        interaction = InteractionContext(channel=channel, status=str(status).upper(), started_at=s_et, ended_at=e_et, clean_transcript=clean, agent_names=agent_names_tuple, agent_emails=agent_emails_tuple)
        text_lines = [f"{channel} FINGERPRINT", f"Channel: {channel}", "Interaction (US Eastern): " + self._fmt(s_et) + " to " + self._fmt(e_et), "Issue discussion:", issue_text]
        return FingerprintResult("\n".join(text_lines), interaction, ids, issue_excerpt=issue_excerpt, location_statements=locations, caller_requested_pauses=tuple(pauses), search_window_start=lo, search_window_end=hi)

    @staticmethod
    def _clip(value: object, limit: int) -> str:
        text = str(value or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip() + " ..."

    @staticmethod
    def _fmt(value: datetime | None) -> str:
        return value.strftime("%Y-%m-%d %H:%M") if value else "unknown"

    @staticmethod
    def _mmss(seconds: float) -> str:
        minutes, secs = divmod(int(float(seconds)), 60)
        return f"{minutes:02d}:{secs:02d}"
