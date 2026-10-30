from pathlib import Path
import tempfile

import pytest

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from modules.exceptions import SecurityError, ValidationError
from modules.validation import resolve_artifact_path, validate_safe_filename, validate_uuid


def test_platform_limits():
    assert MAX_FILE_SIZE_MB == 500
    assert MAX_AUDIO_DURATION_SECONDS == 14_400


def test_valid_uuid_normalized():
    assert validate_uuid(" 123E4567-E89B-12D3-A456-426614174000 ") == "123e4567-e89b-12d3-a456-426614174000"


def test_invalid_uuid():
    with pytest.raises(ValidationError):
        validate_uuid("not-a-uuid")


def test_safe_filename():
    assert validate_safe_filename("report_2026.html") == "report_2026.html"


def test_artifact_path_stays_in_root():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert resolve_artifact_path(root, "safe.bin").parent == root.resolve()
        with pytest.raises(ValidationError):
            resolve_artifact_path(root, "../escape.bin")


def test_rejects_windows_traversal():
    with pytest.raises(ValidationError):
        validate_safe_filename("..\\escape.bin")
