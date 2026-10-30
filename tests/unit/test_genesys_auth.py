from unittest.mock import Mock

import pytest
import requests

from services.genesys_auth import (
    GenesysAuthConfiguration,
    GenesysAuthService,
    GenesysAuthenticationError,
    GenesysConfigurationError,
    GenesysOrganizationError,
    TokenOptions,
    normalize_region,
)


class MockResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.parametrize(
    ("input_region", "expected"),
    [
        (None, "mypurecloud.com"),
        ("mypurecloud.com", "mypurecloud.com"),
        ("https://login.mypurecloud.com", "mypurecloud.com"),
        ("apps.intelegrate.com", "intelegrate.com"),
        ("API.MYPURECLOUD.COM/anything", "mypurecloud.com"),
        (" login.euw2.pure.cloud ", "euw2.pure.cloud"),
    ],
)
def test_normalize_region(input_region, expected):
    assert normalize_region(input_region) == expected


def test_environment_configuration_and_manual_token():
    config = GenesysAuthConfiguration.from_environment({
        "GENESYS_REGION": "https://apps.mypurecloud.com",
        "GENESYS_CLIENT_ID": "client-id",
        "GENESYS_CLIENT_SECRET": "secret-value",
        "GENESYS_MANUAL_TOKEN": "Bearer dev-token",
        "GENESYS_VERIFY_ORGANIZATION": "false",
        "GENESYS_HTTP_TIMEOUT_SECONDS": "8",
        "GENESYS_TOKEN_CACHE_MARGIN_SECONDS": "20",
    })
    service = GenesysAuthService(config, session=Mock())

    result = service.get_access_token()

    assert result.access_token == "dev-token"
    assert result.region == "mypurecloud.com"
    assert result.source == "manual"
    assert result.organization is None
    assert config.timeout_seconds == 8
    assert config.cache_refresh_margin_seconds == 20


def test_environment_invalid_timeout_is_structured_configuration_error():
    with pytest.raises(GenesysConfigurationError) as exc:
        GenesysAuthConfiguration.from_environment({"GENESYS_HTTP_TIMEOUT_SECONDS": "not-a-number"})
    assert exc.value.code == "GENESYS_CONFIGURATION_ERROR"


def test_client_credentials_success_and_cache_hit():
    clock = iter([1000.0, 1001.0, 1002.0])
    clock_function = lambda: next(clock)
    session = Mock()
    session.post.return_value = MockResponse(200, {"access_token": "oauth-token", "expires_in": 3600})
    config = GenesysAuthConfiguration(region="mypurecloud.com", client_id="id", client_secret="secret", manual_token=None, verify_org=False)
    service = GenesysAuthService(config, session=session, clock=clock_function)

    first = service.get_access_token()
    second = service.get_access_token()

    assert first.source == "client_credentials"
    assert second.source == "client_credentials_cached"
    assert second.access_token == "oauth-token"
    assert second.expires_in == 3598
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args[0] == "https://login.mypurecloud.com/oauth/token"
    assert kwargs["auth"] == ("id", "secret")


def test_force_refresh_uses_new_token():
    clock = lambda: 1000.0
    session = Mock()
    session.post.side_effect = [
        MockResponse(200, {"access_token": "token-one", "expires_in": 3600}),
        MockResponse(200, {"access_token": "token-two", "expires_in": 3600}),
    ]
    config = GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=False, cache_refresh_margin_seconds=1)
    service = GenesysAuthService(config, session=session, clock=clock)

    first = service.get_access_token()
    refreshed = service.get_access_token(TokenOptions(force_refresh=True))

    assert first.access_token == "token-one"
    assert refreshed.access_token == "token-two"
    assert session.post.call_count == 2


def test_missing_credentials_is_configuration_error():
    service = GenesysAuthService(
        GenesysAuthConfiguration(manual_token=None, client_id=None, client_secret=None, verify_org=False),
        session=Mock(),
    )
    with pytest.raises(GenesysConfigurationError) as exc:
        service.get_access_token()
    assert exc.value.to_dict()["code"] == "GENESYS_CONFIGURATION_ERROR"


def test_token_http_error_is_structured():
    session = Mock()
    session.post.return_value = MockResponse(401, text="invalid client")
    service = GenesysAuthService(
        GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=False),
        session=session,
    )

    with pytest.raises(GenesysAuthenticationError) as exc:
        service.get_access_token()

    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid client"
    assert "secret" not in str(exc.value.to_dict())


def test_token_network_error_is_structured():
    session = Mock()
    session.post.side_effect = requests.ConnectionError("socket failed")
    service = GenesysAuthService(
        GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=False),
        session=session,
    )

    with pytest.raises(GenesysAuthenticationError) as exc:
        service.get_access_token()

    assert exc.value.code == "GENESYS_AUTHENTICATION_ERROR"


def test_token_response_missing_access_token():
    session = Mock()
    session.post.return_value = MockResponse(200, {"expires_in": 3600})
    service = GenesysAuthService(
        GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=False),
        session=session,
    )
    with pytest.raises(GenesysAuthenticationError, match="did not contain access_token"):
        service.get_access_token()


def test_token_response_invalid_json():
    session = Mock()
    session.post.return_value = MockResponse(200, ValueError("bad json"))
    service = GenesysAuthService(
        GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=False),
        session=session,
    )
    with pytest.raises(GenesysAuthenticationError, match="valid JSON"):
        service.get_access_token()


def test_organization_verification_is_attached_to_token():
    session = Mock()
    session.post.return_value = MockResponse(200, {"access_token": "oauth-token", "expires_in": 3600})
    session.get.return_value = MockResponse(200, {"id": "org-1", "name": "Example Org"})
    service = GenesysAuthService(
        GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=True),
        session=session,
    )

    result = service.get_access_token()

    assert result.organization is not None
    assert result.organization.id == "org-1"
    assert result.organization.name == "Example Org"
    session.get.assert_called_once()
    assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer oauth-token"


def test_manual_token_organization_verification():
    session = Mock()
    session.get.return_value = MockResponse(200, {"id": "org-1", "name": "Test Org"})
    service = GenesysAuthService(
        GenesysAuthConfiguration(manual_token="Bearer manual-token", verify_org=True),
        session=session,
    )
    result = service.get_access_token()
    assert result.source == "manual"
    assert result.organization.name == "Test Org"


def test_organization_verification_http_error():
    session = Mock()
    session.post.return_value = MockResponse(200, {"access_token": "token", "expires_in": 3600})
    session.get.return_value = MockResponse(403, text="forbidden")
    service = GenesysAuthService(
        GenesysAuthConfiguration(client_id="id", client_secret="secret", manual_token=None, verify_org=True),
        session=session,
    )

    with pytest.raises(GenesysOrganizationError) as exc:
        service.get_access_token()

    assert exc.value.status_code == 403
    assert exc.value.code == "GENESYS_ORGANIZATION_ERROR"


def test_verify_organization_accepts_result_or_string():
    session = Mock()
    session.get.return_value = MockResponse(200, {"name": "Test Org"})
    config = GenesysAuthConfiguration(region="euw2.pure.cloud", verify_org=True)
    service = GenesysAuthService(config, session=session)

    organization = service.verify_organization("token-value")

    assert organization.name == "Test Org"
    assert session.get.call_args.args[0] == "https://api.euw2.pure.cloud/api/v2/organizations/me"


def test_cache_invalidate_all_and_by_region_or_client():
    clock = lambda: 1000.0
    session = Mock()
    session.post.side_effect = lambda *args, **kwargs: MockResponse(200, {"access_token": f"token-{session.post.call_count}", "expires_in": 3600})
    config = GenesysAuthConfiguration(client_id="id-1", client_secret="secret", manual_token=None, verify_org=False, cache_refresh_margin_seconds=1)
    service = GenesysAuthService(config, session=session, clock=clock)

    service.get_access_token()
    assert service.invalidate(region="mypurecloud.com", client_id="id-1") == 1
    assert service.invalidate() == 0
