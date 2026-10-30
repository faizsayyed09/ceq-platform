from services.audit import AuditService
from services.matching import FingerprintService, TicketMatchingService
from services.knowledge import KnowledgeService


def test_fingerprint_is_deterministic():
    service = FingerprintService()
    first = service.fingerprint("Agent reset password for employee")
    second = service.fingerprint("Agent reset password for employee")
    assert first == second
    assert len(first["transcript_hash_fingerprint"]) == 64


def test_ticket_matching():
    result = TicketMatchingService().match(
        "password reset employee account",
        [{"ticket_id": "INC001", "description": "Employee needed password reset account unlock"}],
        threshold=0.2,
    )
    assert result["match_count"] == 1
    assert result["matches"][0]["ticket_id"] == "INC001"


def test_knowledge_search():
    result = KnowledgeService().search("password reset", [{"article_id": "KB1", "title": "Password Reset", "body": "Reset an account password"}])
    assert result["result_count"] == 1


def test_audit_result_parser_score():
    result = AuditService().parse_result('{"score": 96, "findings": []}')
    assert result["score"] == 96
