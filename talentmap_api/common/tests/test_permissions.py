import pytest

from unittest.mock import Mock
from model_mommy import mommy

from talentmap_api.common.permissions import isDjangoGroupMember, isDjangoGroupMemberOrReadOnly
from talentmap_api.common.decorators import respect_instance_signalling


# ---------------------------------------------------------------------------
# isDjangoGroupMember
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_is_django_group_member_grants_access():
    user = mommy.make('auth.User')
    group = mommy.make('auth.Group', name='editors')
    group.user_set.add(user)

    perm_class = isDjangoGroupMember('editors')()
    request = Mock(user=user)
    assert perm_class.has_permission(request, None) is True


@pytest.mark.django_db()
def test_is_django_group_member_denies_non_member():
    user = mommy.make('auth.User')
    mommy.make('auth.Group', name='editors')

    perm_class = isDjangoGroupMember('editors')()
    request = Mock(user=user)
    assert perm_class.has_permission(request, None) is False


@pytest.mark.django_db()
def test_is_django_group_member_superuser_bypass():
    user = mommy.make('auth.User')
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(user)

    mommy.make('auth.Group', name='editors')

    perm_class = isDjangoGroupMember('editors')()
    request = Mock(user=user)
    assert perm_class.has_permission(request, None) is True


@pytest.mark.django_db()
def test_is_django_group_member_nonexistent_group():
    user = mommy.make('auth.User')
    perm_class = isDjangoGroupMember('nonexistent')()
    request = Mock(user=user)
    assert perm_class.has_permission(request, None) is False


# ---------------------------------------------------------------------------
# isDjangoGroupMemberOrReadOnly
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_read_only_allows_safe_methods():
    user = mommy.make('auth.User')
    mommy.make('auth.Group', name='editors')

    perm_class = isDjangoGroupMemberOrReadOnly('editors')()

    for method in ('GET', 'HEAD', 'OPTIONS'):
        request = Mock(user=user, method=method)
        assert perm_class.has_permission(request, None) is True


@pytest.mark.django_db()
def test_read_only_denies_unsafe_for_non_member():
    user = mommy.make('auth.User')
    mommy.make('auth.Group', name='editors')

    perm_class = isDjangoGroupMemberOrReadOnly('editors')()

    for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        request = Mock(user=user, method=method)
        assert perm_class.has_permission(request, None) is False


@pytest.mark.django_db()
def test_read_only_allows_member_unsafe():
    user = mommy.make('auth.User')
    group = mommy.make('auth.Group', name='editors')
    group.user_set.add(user)

    perm_class = isDjangoGroupMemberOrReadOnly('editors')()
    request = Mock(user=user, method='POST')
    assert perm_class.has_permission(request, None) is True


@pytest.mark.django_db()
def test_read_only_superuser_bypass_unsafe():
    user = mommy.make('auth.User')
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(user)

    mommy.make('auth.Group', name='editors')

    perm_class = isDjangoGroupMemberOrReadOnly('editors')()
    request = Mock(user=user, method='DELETE')
    assert perm_class.has_permission(request, None) is True


# ---------------------------------------------------------------------------
# respect_instance_signalling decorator
# ---------------------------------------------------------------------------

def test_respect_signalling_runs_when_no_flag():
    called = []

    @respect_instance_signalling()
    def handler(sender, instance, **kwargs):
        called.append(True)

    instance = Mock(spec=[])  # no _disable_signals attribute
    handler(sender=None, instance=instance)
    assert called == [True]


def test_respect_signalling_skips_when_disabled():
    called = []

    @respect_instance_signalling()
    def handler(sender, instance, **kwargs):
        called.append(True)

    instance = Mock(_disable_signals=True)
    result = handler(sender=None, instance=instance)
    assert called == []
    assert result is None


def test_respect_signalling_runs_when_enabled():
    called = []

    @respect_instance_signalling()
    def handler(sender, instance, **kwargs):
        called.append(True)
        return 'ok'

    instance = Mock(_disable_signals=False)
    result = handler(sender=None, instance=instance)
    assert called == [True]
    assert result == 'ok'
