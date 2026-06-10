import pytest

from model_mommy import mommy
from rest_framework import status

from django.core.management import call_command
from django.core.management.base import CommandError


# ---------------------------------------------------------------------------
# PermissionGroupView (list / retrieve)
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_group_list(authorized_client, authorized_user):
    groups = mommy.make('auth.Group', _quantity=3)
    response = authorized_client.get('/api/v1/permission/group/')
    assert response.status_code == status.HTTP_200_OK
    returned_ids = {g["id"] for g in response.data["results"]}
    for g in groups:
        assert g.id in returned_ids


@pytest.mark.django_db()
def test_group_retrieve(authorized_client, authorized_user):
    group = mommy.make('auth.Group')
    perm = mommy.make('auth.Permission')
    group.permissions.add(perm)

    response = authorized_client.get(f'/api/v1/permission/group/{group.id}/')
    assert response.status_code == status.HTTP_200_OK
    assert response.data["name"] == group.name
    assert any(p["id"] == perm.id for p in response.data["permissions"])


@pytest.mark.django_db()
def test_group_retrieve_not_found(authorized_client, authorized_user):
    response = authorized_client.get('/api/v1/permission/group/99999/')
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db()
def test_group_list_unauthenticated(client):
    response = client.get('/api/v1/permission/group/')
    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# PermissionGroupControls (get / put / delete membership)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_group_controls_require_superuser(authorized_client, authorized_user):
    group = mommy.make('auth.Group')
    target_user = mommy.make('auth.User')

    for method in ('get', 'put', 'delete'):
        response = getattr(authorized_client, method)(
            f'/api/v1/permission/group/{group.id}/user/{target_user.profile.id}/'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db(transaction=True)
def test_group_controls_add_user(authorized_client, authorized_user):
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(authorized_user)

    group = mommy.make('auth.Group')
    target_user = mommy.make('auth.User')

    response = authorized_client.put(
        f'/api/v1/permission/group/{group.id}/user/{target_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert group.user_set.filter(pk=target_user.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_group_controls_remove_user(authorized_client, authorized_user):
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(authorized_user)

    group = mommy.make('auth.Group')
    target_user = mommy.make('auth.User')
    group.user_set.add(target_user)

    response = authorized_client.delete(
        f'/api/v1/permission/group/{group.id}/user/{target_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not group.user_set.filter(pk=target_user.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_group_controls_check_membership_present(authorized_client, authorized_user):
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(authorized_user)

    group = mommy.make('auth.Group')
    target_user = mommy.make('auth.User')
    group.user_set.add(target_user)

    response = authorized_client.get(
        f'/api/v1/permission/group/{group.id}/user/{target_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db(transaction=True)
def test_group_controls_check_membership_absent(authorized_client, authorized_user):
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(authorized_user)

    group = mommy.make('auth.Group')
    target_user = mommy.make('auth.User')

    response = authorized_client.get(
        f'/api/v1/permission/group/{group.id}/user/{target_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db(transaction=True)
def test_group_controls_nonexistent_group(authorized_client, authorized_user):
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(authorized_user)

    target_user = mommy.make('auth.User')
    response = authorized_client.get(
        f'/api/v1/permission/group/99999/user/{target_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db(transaction=True)
def test_group_controls_nonexistent_user(authorized_client, authorized_user):
    superuser_group = mommy.make('auth.Group', name='superuser')
    superuser_group.user_set.add(authorized_user)

    group = mommy.make('auth.Group')
    response = authorized_client.get(
        f'/api/v1/permission/group/{group.id}/user/99999/'
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# UserPermissionView (list / retrieve)
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_user_permission_list(authorized_client, authorized_user):
    group = mommy.make('auth.Group')
    group.user_set.add(authorized_user)

    response = authorized_client.get('/api/v1/permission/user/')
    assert response.status_code == status.HTTP_200_OK
    assert group.name in response.data["groups"]
    assert "user" in response.data
    assert "permissions" in response.data


@pytest.mark.django_db()
def test_user_permission_list_no_groups(authorized_client, authorized_user):
    response = authorized_client.get('/api/v1/permission/user/')
    assert response.status_code == status.HTTP_200_OK
    assert response.data["groups"] == []


@pytest.mark.django_db()
def test_user_permission_retrieve_by_profile(authorized_client, authorized_user):
    group = mommy.make('auth.Group')
    group.user_set.add(authorized_user)

    response = authorized_client.get(
        f'/api/v1/permission/user/{authorized_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_200_OK
    assert group.name in response.data["groups"]


@pytest.mark.django_db()
def test_user_permission_retrieve_other_user(authorized_client, authorized_user):
    other_user = mommy.make('auth.User')
    group = mommy.make('auth.Group')
    group.user_set.add(other_user)

    response = authorized_client.get(
        f'/api/v1/permission/user/{other_user.profile.id}/'
    )
    assert response.status_code == status.HTTP_200_OK
    assert group.name in response.data["groups"]


@pytest.mark.django_db()
def test_user_permission_retrieve_not_found(authorized_client, authorized_user):
    response = authorized_client.get('/api/v1/permission/user/99999/')
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db()
def test_user_permission_unauthenticated(client):
    response = client.get('/api/v1/permission/user/')
    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# modify_group management command
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_modify_group_add():
    user = mommy.make('auth.User', email='test@example.com')
    group = mommy.make('auth.Group', name='test_group')

    call_command('modify_group', 'add', 'test@example.com', 'test_group')
    assert group in user.groups.all()


@pytest.mark.django_db()
def test_modify_group_remove():
    user = mommy.make('auth.User', email='test@example.com')
    group = mommy.make('auth.Group', name='test_group')
    user.groups.add(group)

    call_command('modify_group', 'remove', 'test@example.com', 'test_group')
    assert group not in user.groups.all()


@pytest.mark.django_db()
def test_modify_group_nonexistent_group():
    mommy.make('auth.User', email='test@example.com')
    with pytest.raises(Exception):
        call_command('modify_group', 'add', 'test@example.com', 'no_such_group')


@pytest.mark.django_db()
def test_modify_group_nonexistent_user():
    mommy.make('auth.Group', name='test_group')
    with pytest.raises(Exception):
        call_command('modify_group', 'add', 'nobody@example.com', 'test_group')


def test_modify_group_invalid_mode():
    with pytest.raises(CommandError):
        call_command('modify_group', 'invalid', 'a@b.com', 'grp')
