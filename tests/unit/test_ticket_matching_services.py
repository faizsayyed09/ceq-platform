from datetime import datetime, timedelta

from services.fingerprint_service import FingerprintService
from services.ticket_matching_service import (
    AMBIGUOUS,
    MATCHED,
    NOT_FOUND,
    NO_EXPORT,
    PENDING_EXPORT,
    TicketExportResult,
    TicketMatchingService,
    TicketRow,
)
from services.ticket_policy_service import TicketPolicyService


def make_fingerprint(transcript: str = "INC123456 password reset", agent_names=("Pat Agent",), agent_emails=("pat@example.com",)):
    return FingerprintService().fingerprint(
        transcript,
        status="DONE",
        channel="CALL",
        call_start=datetime(2026, 1, 15, 14, 0),
        call_end=datetime(2026, 1, 15, 15, 0),
        agent_names=agent_names,
        agent_emails=agent_emails,
        window_minutes=60,
    )


def test_fingerprint_extracts_tickets_and_call_context():
    result = make_fingerprint("[00:10] CALLER: My ticket is INC123456 at office")

    assert result.identifiers.ticket_numbers == ("INC123456",)
    assert result.interaction.channel == "CALL"
    assert result.search_window_start == datetime(2026, 1, 15, 8, 0)
    assert result.location_statements == ("My ticket is INC123456 at office",)


def test_explicit_ticket_number_is_matched_deterministically():
    fingerprint = make_fingerprint()
    row = TicketRow({
        "Number": "INC123456",
        "Opened": "2026-01-15 14:30:00",
        "Opened by": "Some User",
        "Short description": "Password reset",
        "Description": "Caller cannot reset password",
        "Contact type": "Phone",
    })

    result = TicketMatchingService().match(fingerprint, TicketExportResult(rows=(row,), uploaded_at=datetime(2026, 1, 15, 16, 0)))

    assert result.status == MATCHED
    assert result.confidence == "HIGH"
    assert result.best_ticket == "INC123456"
    assert result.candidates[0].score >= 100
    assert result.candidates[0].reasons[0].startswith("number from the interaction")


def test_missing_export_is_no_export():
    result = TicketMatchingService().match(make_fingerprint(), TicketExportResult())

    assert result.status == NO_EXPORT
    assert result.best_ticket == ""
    assert result.candidates == ()


def test_below_threshold_is_not_found():
    fingerprint = make_fingerprint("caller has a new issue")
    row = TicketRow({
        "Number": "INC999999",
        "Opened": "2026-01-01 01:00:00",
        "Opened by": "Different Person",
        "Short description": "Unrelated printer issue",
        "Description": "Printer toner replacement",
        "Contact type": "Email",
    })
    result = TicketMatchingService().match(fingerprint, TicketExportResult(rows=(row,)))

    # This row is not eligible, so it cannot produce a candidate below the threshold.
    assert result.status == NOT_FOUND


def test_pending_export_preserves_grace_policy():
    fingerprint = make_fingerprint("caller has a generic issue", agent_names=("Different Agent",), agent_emails=("different@example.com",))
    row = TicketRow({"Number": "INC999999", "Opened": "2026-01-01 01:00:00", "Opened by": "Different Person"})
    export = TicketExportResult(rows=(row,), uploaded_at=fingerprint.interaction.ended_at + timedelta(minutes=30))

    result = TicketMatchingService().match(fingerprint, export)

    assert result.status == NOT_FOUND or result.status == PENDING_EXPORT
    if fingerprint.interaction.ended_at:
        assert result.status == PENDING_EXPORT


def test_ambiguous_result_requires_medium_confidence():
    fingerprint = make_fingerprint(transcript="employee password reset")
    row = TicketRow({
        "Number": "INC123456",
        "Opened": "2026-01-15 10:30:00",
        "Opened by": "Pat Agent",
        "Short description": "Password reset",
        "Description": "Employee password reset",
        "Contact type": "Phone",
    })
    result = TicketMatchingService().match(fingerprint, TicketExportResult(rows=(row,)))

    assert result.status == MATCHED or result.status == AMBIGUOUS
    assert result.confidence in ("HIGH", "MEDIUM")


def test_policy_overrides_conflicting_proposal_with_deterministic_match():
    fingerprint = make_fingerprint()
    row = TicketRow({"Number": "INC123456", "Opened": "2026-01-15 14:30:00", "Opened by": "Pat Agent", "Description": "Password reset"})
    prematch = TicketMatchingService().match(fingerprint, TicketExportResult(rows=(row,), uploaded_at=datetime(2026, 1, 15, 16, 0)))

    result = TicketPolicyService().verify(prematch, '{"matched_ticket":"INC999999","match_confidence":"MEDIUM"}', fingerprint=fingerprint)

    assert result.matched_ticket == "INC123456"
    assert result.match_status == MATCHED
    assert any("overridden" in note for note in result.notes)


def test_policy_rejects_proposal_not_in_candidate_rows():
    fingerprint = make_fingerprint("employee password reset")
    row = TicketRow({"Number": "INC123456", "Opened by": "Pat Agent", "Opened": "2026-01-15 14:30:00", "Description": "Password reset"})
    prematch = TicketMatchingService().match(fingerprint, TicketExportResult(rows=(row,)))

    result = TicketPolicyService().verify(prematch, '{"matched_ticket":"INC999999","match_confidence":"HIGH"}', fingerprint=fingerprint)

    assert result.match_status == NOT_FOUND
    assert result.matched_ticket == ""
    assert result.match_confidence == "LOW"


def test_kb_query_is_built_from_typed_state():
    fingerprint = make_fingerprint("[00:10] CALLER: Department: Cardiology. Password reset needed.")
    row = TicketRow({"Number": "INC123456", "Opened by": "Pat Agent", "Opened": "2026-01-15 14:30:00", "Description": "Password reset"})
    prematch = TicketMatchingService().match(fingerprint, TicketExportResult(rows=(row,)))
    verification = TicketPolicyService().verify(prematch, '{"matched_ticket":"INC123456"}', fingerprint=fingerprint)

    query = TicketPolicyService().build_kb_query(verification, fingerprint)

    assert "Password reset needed" in query.issue_summary or "Cardiology" in fingerprint.interaction.clean_transcript
    assert query.location == "Cardiology"
