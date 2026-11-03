import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from contracts.artifact import ArtifactMetadata, ArtifactType, RetentionAction, RetentionPolicy
from modules.exceptions import ArtifactNotFoundError, ArtifactValidationError
from providers.artifact import AzureBlobArtifactProvider, LocalArtifactProvider, S3CompatibleArtifactProvider
from services.artifact_store import ArtifactStoreService
import providers.artifact as artifact_module


def run(coro):
    return asyncio.run(coro)


def test_local_save_read_and_exists(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)
    metadata = run(service.save(ArtifactType.REPORT, "audit-1", "report.html", b"<html>ok</html>", content_type="text/html"))

    assert metadata.size_bytes == len(b"<html>ok</html>")
    assert run(service.exists(metadata.key)) is True
    assert run(service.read(metadata.key)) == b"<html>ok</html>"


def test_local_delete(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)
    metadata = run(service.save(ArtifactType.RECORDING, "11111111-2222-3333-4444-555555555555", "call.wav", b"RIFFaudio"))

    assert run(service.delete(metadata.key)) is True
    assert run(service.exists(metadata.key)) is False
    assert run(service.delete(metadata.key)) is False


def test_retention_expiry(tmp_path):
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    service = ArtifactStoreService(storage_root=tmp_path, clock=lambda: created)
    policy = RetentionPolicy(RetentionAction.DELETE_AFTER_EXPIRY, retention_days=2)
    metadata = run(service.save(ArtifactType.TRANSCRIPT, "audit-1", "transcript.txt", b"hello", retention=policy))

    assert run(service.apply_retention(created + timedelta(days=1))) == 0
    assert run(service.apply_retention(created + timedelta(days=3))) == 1
    assert run(service.exists(metadata.key)) is False


def test_delete_after_processing(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)
    policy = RetentionPolicy(RetentionAction.DELETE_AFTER_PROCESSING)
    metadata = run(service.save(ArtifactType.RECORDING, "audit-1", "call.wav", b"audio", retention=policy))

    assert run(service.delete_after_processing(metadata.key)) is True
    assert run(service.exists(metadata.key)) is False


def test_deterministic_key_generation(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)
    first = service.generate_key("report", "audit-1", "report.html")
    second = service.generate_key(ArtifactType.REPORT, "audit-1", "report.html")

    assert first == second
    assert first.as_posix().startswith("report/audit-1/")


def test_traversal_prevention(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)

    with pytest.raises(ArtifactValidationError):
        service.generate_key(ArtifactType.REPORT, "audit-1", "../outside.html")

    with pytest.raises(ArtifactValidationError):
        service.generate_key(ArtifactType.REPORT, "audit-1", "folder\\outside.html")


def test_filename_validation(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)

    for filename in ("", " report.html", "bad/name.html", "bad;name.html", "."):
        with pytest.raises(ArtifactValidationError):
            service.generate_key(ArtifactType.REPORT, "audit-1", filename)


def test_download_link_and_missing_read(tmp_path):
    service = ArtifactStoreService(storage_root=tmp_path)
    metadata = run(service.save(ArtifactType.TRANSCRIPT, "audit-1", "transcript.txt", b"text"))

    link = run(service.create_download_link(metadata.key, expires_in_seconds=60))
    assert link.url.startswith("local://artifact/")
    assert link.expires_at is not None

    provider = LocalArtifactProvider(tmp_path)
    missing = service.generate_key(ArtifactType.TRANSCRIPT, "audit-1", "missing.txt")
    with pytest.raises(ArtifactNotFoundError):
        run(provider.read(missing))


def test_azure_blob_provider_managed_identity_read_write(monkeypatch, tmp_path):
    class Token:
        token = "test-token"

    class Credential:
        def get_token(self, scope):
            assert scope == "https://storage.azure.com/.default"
            return Token()

    class Response:
        status_code = 200
        content = b"blob-data"
        text = "<EnumerationResults />"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(artifact_module.requests, "put", lambda *args, **kwargs: Response())
    monkeypatch.setattr(artifact_module.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(artifact_module.requests, "head", lambda *args, **kwargs: Response())
    monkeypatch.setattr(artifact_module.requests, "delete", lambda *args, **kwargs: Response())

    provider = AzureBlobArtifactProvider(
        account_url="https://account.blob.core.windows.net",
        container="ceq-kb",
        credential=Credential(),
    )
    key = ArtifactStoreService(storage_root=tmp_path).generate_key("report", "audit-1", "report.html")
    metadata = ArtifactMetadata(
        key=key,
        content_type="text/html",
        retention=RetentionPolicy(RetentionAction.DELETE_AFTER_PROCESSING),
    )
    saved = run(provider.save(key, b"<html>ok</html>", metadata=metadata))
    assert saved.checksum
    assert run(provider.read(key)) == b"blob-data"
    assert run(provider.exists(key)) is True
    assert run(provider.delete(key)) is True


def test_future_provider_interfaces_are_explicit(tmp_path):
    azure = AzureBlobArtifactProvider(container="artifacts")
    s3 = S3CompatibleArtifactProvider(bucket="artifacts")
    key = ArtifactStoreService(storage_root=tmp_path).generate_key("report", "audit-1", "report.html")

    with pytest.raises(NotImplementedError, match="Azure Blob"):
        run(azure.read(key))
    with pytest.raises(NotImplementedError, match="S3-compatible"):
        run(s3.read(key))
