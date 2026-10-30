import pytest

from modules.exceptions import SecurityError, ValidationError
from services.genesys_auth import GenesysAuthService


def test_rejects_invalid_region():
    service = GenesysAuthService(client_id="id", client_secret="secret")
    with pytest.raises(ValidationError):
        service.authenticate(region="example.com")


def test_manual_token_disabled_by_default():
    service = GenesysAuthService()
    with pytest.raises(SecurityError):
        service.authenticate(manual_token="testing-token")


def test_manual_token_testing_mode():
    service = GenesysAuthService(allow_manual_token_testing=True)
    result = service.authenticate(region="mypurecloud.com", manual_token="Bearer test-token")
    assert result["access_token"] == "test-token"
    assert result["source"] == "manual"
