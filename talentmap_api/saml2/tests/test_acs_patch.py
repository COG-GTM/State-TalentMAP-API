import pytest
from unittest.mock import patch, Mock, MagicMock, PropertyMock

from django.core.exceptions import SuspiciousOperation
from django.test import RequestFactory

from saml2.response import (
    StatusError, StatusAuthnFailed, SignatureError, StatusRequestDenied,
    UnsolicitedResponse,
)
from saml2.validate import ResponseLifetimeExceed, ToEarly
from saml2.sigver import MissingKey


MODULE = 'talentmap_api.saml2.acs_patch'


def _post_request(data=None):
    """Build a POST request with a session via RequestFactory."""
    factory = RequestFactory()
    request = factory.post('/saml2/acs/', data=data or {})
    request.session = {}
    return request


def _make_mock_client():
    """Return a mock Saml2Client with the attributes acs_patch reads."""
    client = MagicMock()
    client.allow_unsolicited = False
    client.want_assertions_signed = False
    client.want_response_signed = False
    client.service_urls.return_value = ['https://sp.example.com/acs/']
    client.config.entityid = 'https://sp.example.com/metadata/'
    client.config.attribute_converters = []
    client.config.allow_unknown_attributes = True
    return client


# -----------------------------------------------------------------------
# Patch stack shared by most tests – patches external deps so
# assertion_consumer_service can be imported and called without a real
# SAML IdP / Django SAML config.
# -----------------------------------------------------------------------
COMMON_PATCHES = [
    patch(MODULE + '.get_config', return_value=MagicMock()),
    patch(MODULE + '.get_custom_setting', side_effect=lambda key, default=None: default),
    patch(MODULE + '.IdentityCache', return_value=MagicMock()),
    patch(MODULE + '.OutstandingQueriesCache'),
    patch(MODULE + '.Saml2Client', side_effect=lambda *a, **kw: _make_mock_client()),
]


# -----------------------------------------------------------------------
# 1. Missing SAMLResponse → SuspiciousOperation
# -----------------------------------------------------------------------
class TestMissingSAMLResponse:

    def test_missing_saml_response_raises_suspicious_operation(self):
        """POST without SAMLResponse key must raise SuspiciousOperation."""
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={})
        mocks = [p.start() for p in COMMON_PATCHES]
        try:
            with pytest.raises(SuspiciousOperation):
                assertion_consumer_service(request)
        finally:
            for p in COMMON_PATCHES:
                p.stop()


# -----------------------------------------------------------------------
# 2. Each SAML parsing error returns fail_acs_response
# -----------------------------------------------------------------------
class TestSAMLParsingErrors:

    @pytest.mark.parametrize('exc_class', [
        StatusError,
        ToEarly,
    ])
    def test_status_error_or_too_early(self, exc_class):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        # Make _parse_response raise the target exception
        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = exc_class()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_response_lifetime_exceed(self):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = ResponseLifetimeExceed()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_signature_error(self):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = SignatureError()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_status_authn_failed(self):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = StatusAuthnFailed()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_status_request_denied(self):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = StatusRequestDenied()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_missing_key(self):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = MissingKey()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_unsolicited_response(self):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.side_effect = UnsolicitedResponse()
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()

    def test_none_response_returns_fail_acs(self):
        """When _parse_response returns None, fail_acs_response is called."""
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})
        sentinel = Mock(name='fail_response')

        patches = COMMON_PATCHES + [
            patch(MODULE + '.fail_acs_response', return_value=sentinel),
        ]
        for p in patches:
            p.start()

        mock_client = _make_mock_client()
        mock_client._parse_response.return_value = None
        with patch(MODULE + '.Saml2Client', return_value=mock_client):
            result = assertion_consumer_service(request)

        assert result is sentinel
        for p in patches:
            p.stop()


# -----------------------------------------------------------------------
# 3. Successful SAML auth → user created/updated, token created, redirect
# -----------------------------------------------------------------------
@pytest.mark.django_db()
class TestSuccessfulSAMLAuth:

    def _run_success(self, existing_user=False):
        from talentmap_api.saml2.acs_patch import assertion_consumer_service
        from django.contrib.auth.models import User

        if existing_user:
            User.objects.create_user(
                username='jane.doe@example.com',
                email='jane.doe@example.com',
                first_name='Old',
                last_name='Name',
            )

        request = _post_request(data={'SAMLResponse': 'dummyxml'})

        mock_response = MagicMock()
        mock_response.ava = {
            'name': ['jane.doe@example.com'],
            'givenname': ['Jane'],
            'surname': ['Doe'],
        }

        mock_client = _make_mock_client()
        mock_client._parse_response.return_value = mock_response

        patches = COMMON_PATCHES + [
            patch(MODULE + '._set_subject_id'),
        ]
        for p in patches:
            p.start()

        with patch(MODULE + '.Saml2Client', return_value=mock_client), \
             patch(MODULE + '.settings') as mock_settings:
            mock_settings.LOGIN_REDIRECT_URL = 'https://app.example.com/login'
            result = assertion_consumer_service(request)

        for p in patches:
            p.stop()

        return result

    def test_redirect_contains_token(self):
        result = self._run_success()
        assert result.status_code == 302
        assert 'tmApiToken=' in result.url
        assert result.url.startswith('https://app.example.com/login?tmApiToken=')

    def test_user_created_from_saml_attributes(self):
        from django.contrib.auth.models import User

        self._run_success()
        user = User.objects.get(email='jane.doe@example.com')
        assert user.first_name == 'Jane'
        assert user.last_name == 'Doe'
        assert user.username == 'jane.doe@example.com'

    def test_existing_user_updated(self):
        from django.contrib.auth.models import User

        self._run_success(existing_user=True)
        user = User.objects.get(email='jane.doe@example.com')
        assert user.first_name == 'Jane'
        assert user.last_name == 'Doe'

    def test_token_created_for_user(self):
        from django.contrib.auth.models import User
        from rest_framework_expiring_authtoken.models import ExpiringToken

        self._run_success()
        user = User.objects.get(email='jane.doe@example.com')
        assert ExpiringToken.objects.filter(user=user).exists()

    def test_expired_token_is_rotated(self):
        from django.contrib.auth.models import User
        from rest_framework_expiring_authtoken.models import ExpiringToken

        self._run_success()
        user = User.objects.get(email='jane.doe@example.com')
        token = ExpiringToken.objects.get(user=user)
        old_key = token.key

        # Simulate expired token by patching expired()
        # Don't pass existing_user=True since _run_success already created
        # the user above; get_or_create in acs_patch will find it.
        with patch.object(ExpiringToken, 'expired', return_value=True):
            self._run_success(existing_user=False)

        new_token = ExpiringToken.objects.get(user=user)
        assert new_token.key != old_key


# -----------------------------------------------------------------------
# 4. create_unknown_user parameter handling
# -----------------------------------------------------------------------
@pytest.mark.django_db()
class TestCreateUnknownUserSetting:

    def test_default_attribute_mapping_used_when_setting_absent(self):
        """get_custom_setting default for SAML_ATTRIBUTE_MAPPING is {'uid': ('username',)}."""
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})

        mock_response = MagicMock()
        mock_response.ava = {
            'name': ['test@example.com'],
            'givenname': ['Test'],
            'surname': ['User'],
        }

        mock_client = _make_mock_client()
        mock_client._parse_response.return_value = mock_response

        captured = {}

        original_get_custom_setting = None

        def spy_get_custom_setting(key, default=None):
            captured[key] = default
            return default

        patches = COMMON_PATCHES[:]
        # Override the get_custom_setting patch with our spy
        patches[1] = patch(MODULE + '.get_custom_setting', side_effect=spy_get_custom_setting)
        patches.append(patch(MODULE + '._set_subject_id'))

        for p in patches:
            p.start()

        with patch(MODULE + '.Saml2Client', return_value=mock_client), \
             patch(MODULE + '.settings') as mock_settings:
            mock_settings.LOGIN_REDIRECT_URL = 'https://app.example.com/login'
            assertion_consumer_service(request)

        for p in patches:
            p.stop()

        assert 'SAML_ATTRIBUTE_MAPPING' in captured
        assert captured['SAML_ATTRIBUTE_MAPPING'] == {'uid': ('username', )}
        assert 'SAML_CREATE_UNKNOWN_USER' in captured
        assert captured['SAML_CREATE_UNKNOWN_USER'] is True

    def test_create_unknown_user_true_creates_user(self):
        """When SAML_CREATE_UNKNOWN_USER defaults to True, new users are created."""
        from talentmap_api.saml2.acs_patch import assertion_consumer_service
        from django.contrib.auth.models import User

        request = _post_request(data={'SAMLResponse': 'dummyxml'})

        mock_response = MagicMock()
        mock_response.ava = {
            'name': ['newuser@example.com'],
            'givenname': ['New'],
            'surname': ['Person'],
        }

        mock_client = _make_mock_client()
        mock_client._parse_response.return_value = mock_response

        patches = COMMON_PATCHES + [
            patch(MODULE + '._set_subject_id'),
        ]
        for p in patches:
            p.start()

        with patch(MODULE + '.Saml2Client', return_value=mock_client), \
             patch(MODULE + '.settings') as mock_settings:
            mock_settings.LOGIN_REDIRECT_URL = 'https://app.example.com/login'
            result = assertion_consumer_service(request, create_unknown_user=True)

        for p in patches:
            p.stop()

        assert result.status_code == 302
        assert User.objects.filter(email='newuser@example.com').exists()

    def test_explicit_create_unknown_user_false_passed_through(self):
        """Caller can pass create_unknown_user=False explicitly."""
        from talentmap_api.saml2.acs_patch import assertion_consumer_service

        request = _post_request(data={'SAMLResponse': 'dummyxml'})

        mock_response = MagicMock()
        mock_response.ava = {
            'name': ['another@example.com'],
            'givenname': ['Another'],
            'surname': ['User'],
        }

        mock_client = _make_mock_client()
        mock_client._parse_response.return_value = mock_response

        patches = COMMON_PATCHES + [
            patch(MODULE + '._set_subject_id'),
        ]
        for p in patches:
            p.start()

        with patch(MODULE + '.Saml2Client', return_value=mock_client), \
             patch(MODULE + '.settings') as mock_settings:
            mock_settings.LOGIN_REDIRECT_URL = 'https://app.example.com/login'
            result = assertion_consumer_service(request, create_unknown_user=False)

        for p in patches:
            p.stop()

        # The function still creates via get_or_create on User model
        # regardless of create_unknown_user param (it's read but not
        # used to gate creation in this implementation). Verify no crash.
        assert result.status_code == 302
