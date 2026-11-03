from services.audit import AuditService
from services.matching import FingerprintService, TicketMatchingService
from services.knowledge import KnowledgeService
from modules.config import read_secret_file
from services.matchaos_provider import MatchaOsProvider, MatchaOsConfigurationError


class _MatchaOsSession:
    def __init__(self):
        self.calls = []
        self.response = _JsonResponse()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class _JsonResponse:
    status_code = 200
    headers = {}

    def json(self):
        return {"status": "success"}


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


def test_matcha_api_key_can_be_read_from_mounted_file(tmp_path, monkeypatch):
    secret_path = tmp_path / "matcha.key"
    secret_path.write_text("test-only-key\n", encoding="utf-8")
    monkeypatch.setenv("MATCHA_API_KEY_FILE", str(secret_path))
    monkeypatch.delenv("MATCHA_API_KEY", raising=False)
    assert read_secret_file("MATCHA_API_KEY") == "test-only-key"


def test_matchaos_provider_rejects_legacy_key_family():
    try:
        MatchaOsProvider(
            base_url="https://matchaos.example",
            api_key="mk_live_test",
            user_agent="Mozilla/5.0 test",
        )
    except MatchaOsConfigurationError:
        return
    raise AssertionError("legacy key family should be rejected")


def test_matchaos_provider_folder_and_file_routes(tmp_path):
    session = _MatchaOsSession()
    provider = MatchaOsProvider(
        base_url="https://matchaos.example/api",
        api_key="mos_sk_live_test",
        user_agent="Mozilla/5.0 test",
        session=session,
    )
    provider.list_folders(mission_id="mission-id", limit=10, offset=2)
    provider.create_folder(mission_id="mission-id", name="SNOW REPORT")
    provider.delete_folder(folder_id="folder-id")
    provider.list_files(folder_id="folder-id", limit=10, offset=2)

    test_file = tmp_path / "matchaos-test.txt"
    test_file.write_text("MATCHAOS API lifecycle test.", encoding="utf-8")
    provider.upload_file(folder_id="folder-id", file_path=test_file)
    provider.delete_file(file_id="file-id")

    urls = [url for _method, url, _kwargs in session.calls]
    assert urls == [
        "https://matchaos.example/api/v1/missions/mission-id/folders",
        "https://matchaos.example/api/v1/missions/mission-id/folders",
        "https://matchaos.example/api/v1/folders/folder-id",
        "https://matchaos.example/api/v1/folders/folder-id/files",
        "https://matchaos.example/api/v1/folders/folder-id/files",
        "https://matchaos.example/api/v1/files/file-id",
    ]
