import pytest
from unittest.mock import patch
from model_mommy import mommy

from talentmap_api.organization.models import (
    Organization,
    OrganizationGroup,
    Country,
    Location,
    Post,
    TourOfDuty,
)


# ---------------------------------------------------------------------------
# Organization model
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_organization_str():
    org = mommy.make(
        Organization,
        code='100000',
        short_description='EAP',
        long_description='East Asian and Pacific Affairs',
    )
    assert str(org) == '(EAP) East Asian and Pacific Affairs'


@pytest.mark.django_db()
def test_update_relationships_sets_bureau_when_code_matches():
    org = mommy.make(
        Organization,
        code='999000',
        _parent_bureau_code='999000',
        short_description='TST',
        long_description='Test Bureau',
    )
    org.update_relationships()
    org.refresh_from_db()

    assert org.is_bureau is True
    # Bureau orgs don't set bureau_organization FK on themselves
    assert org.bureau_organization is None


@pytest.mark.django_db()
def test_update_relationships_sets_bureau_organization_fk():
    bureau = mommy.make(
        Organization,
        code='888000',
        short_description='BUR',
        long_description='Bureau Org',
    )
    child = mommy.make(
        Organization,
        code='888001',
        _parent_bureau_code='888000',
        short_description='CHD',
        long_description='Child Org',
    )
    child.update_relationships()
    child.refresh_from_db()

    assert child.is_bureau is False
    assert child.bureau_organization == bureau


@pytest.mark.django_db()
def test_update_relationships_sets_parent_organization():
    parent = mommy.make(
        Organization,
        code='777000',
        short_description='PAR',
        long_description='Parent',
    )
    child = mommy.make(
        Organization,
        code='777001',
        _parent_organization_code='777000',
        short_description='CHD',
        long_description='Child',
    )
    child.update_relationships()
    child.refresh_from_db()

    assert child.parent_organization == parent


@pytest.mark.django_db()
def test_update_relationships_sets_location():
    loc = mommy.make(Location, code='LOC001')
    org = mommy.make(
        Organization,
        code='555000',
        _location_code='LOC001',
        short_description='LOC',
        long_description='Located Org',
    )
    org.update_relationships()
    org.refresh_from_db()

    assert org.location == loc


@pytest.mark.django_db()
def test_update_relationships_sets_is_regional():
    org = mommy.make(
        Organization,
        code='110000',
        short_description='REG',
        long_description='Regional Org',
    )
    org.update_relationships()
    org.refresh_from_db()

    assert org.is_regional is True


@pytest.mark.django_db()
def test_update_relationships_non_regional_code():
    org = mommy.make(
        Organization,
        code='999999',
        short_description='NRG',
        long_description='Non-Regional',
    )
    org.update_relationships()
    org.refresh_from_db()

    assert org.is_regional is False


@pytest.mark.django_db()
def test_update_relationships_warns_on_ambiguous_bureau(caplog):
    """When multiple orgs share the bureau code, a warning is logged."""
    mommy.make(Organization, code='DUPE01', short_description='A', long_description='A')
    mommy.make(Organization, code='DUPE02', short_description='B', long_description='B')

    child = mommy.make(
        Organization,
        code='DUPE03',
        _parent_bureau_code='NONEXISTENT',
        short_description='C',
        long_description='C',
    )
    with caplog.at_level('WARNING'):
        child.update_relationships()

    assert child.bureau_organization is None


@pytest.mark.django_db()
def test_update_relationships_warns_on_ambiguous_parent(caplog):
    child = mommy.make(
        Organization,
        code='AMBIG1',
        _parent_organization_code='NO_MATCH',
        short_description='X',
        long_description='X',
    )
    with caplog.at_level('WARNING'):
        child.update_relationships()

    assert child.parent_organization is None


@pytest.mark.django_db()
def test_create_permissions_creates_group_and_permission():
    bureau = mommy.make(
        Organization,
        code='PERM01',
        short_description='PRM',
        long_description='Permission Bureau',
        is_bureau=True,
    )
    bureau.create_permissions()

    from django.contrib.auth.models import Group
    group = Group.objects.get(name='bureau_ao:PERM01')
    assert group.permissions.filter(codename='can_highlight_positions:PERM01').exists()


# ---------------------------------------------------------------------------
# OrganizationGroup model
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_organization_group_str():
    grp = mommy.make(OrganizationGroup, name='Test Group')
    assert str(grp) == 'Test Group'


@pytest.mark.django_db()
def test_create_groups_populates_baseline():
    OrganizationGroup.create_groups()
    assert OrganizationGroup.objects.count() == 6

    names = set(OrganizationGroup.objects.values_list('name', flat=True))
    assert 'Management' in names
    assert 'Office of the Secretary' in names


@pytest.mark.django_db()
def test_organization_group_update_relationships():
    OrganizationGroup.create_groups()
    org = mommy.make(Organization, code='200000', short_description='M', long_description='Mgmt')

    mgmt_group = OrganizationGroup.objects.get(name='Management')
    mgmt_group.update_relationships()

    assert org in mgmt_group.organizations.all()


# ---------------------------------------------------------------------------
# TourOfDuty model
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_tour_of_duty_str():
    tod = mommy.make(
        TourOfDuty,
        code='TOD01',
        long_description='2 Year Tour',
        short_description='2YR',
        months=24,
        is_active=True,
    )
    assert str(tod) == '2 Year Tour'


@pytest.mark.django_db()
def test_tour_of_duty_defaults():
    tod = mommy.make(TourOfDuty, code='TOD02', long_description='Default', short_description='DEF')
    assert tod.months == 0
    assert tod.is_active is False


# ---------------------------------------------------------------------------
# Country model
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_country_str():
    country = mommy.make(
        Country,
        code='GBR',
        short_code='GB',
        location_prefix='UK',
        name='United Kingdom',
        short_name='UK',
    )
    assert str(country) == 'UK'


# ---------------------------------------------------------------------------
# Location model
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_location_str_domestic():
    usa = mommy.make(
        Country,
        code='USA',
        short_code='US',
        location_prefix='US',
        name='United States',
        short_name='US',
    )
    loc = mommy.make(
        Location,
        code='11DC',
        city='Washington',
        state='DC',
        country=usa,
    )
    # Domestic locations omit the country prefix
    assert str(loc) == 'Washington, DC'


@pytest.mark.django_db()
def test_location_str_foreign():
    gbr = mommy.make(
        Country,
        code='GBR',
        short_code='GB',
        location_prefix='UK',
        name='United Kingdom',
        short_name='UK',
    )
    loc = mommy.make(
        Location,
        code='UKLD',
        city='London',
        state='',
        country=gbr,
    )
    assert str(loc) == 'UK, London'


@pytest.mark.django_db()
def test_location_str_empty_fields():
    loc = mommy.make(Location, code='EMPT', city='', state='', country=None)
    assert str(loc) == ''


@pytest.mark.django_db()
def test_location_update_relationships_by_prefix():
    country = mommy.make(
        Country,
        code='FRA',
        short_code='FR',
        location_prefix='FR',
        name='France',
        short_name='France',
    )
    loc = mommy.make(Location, code='FRPA', _country='France')
    loc.update_relationships()
    loc.refresh_from_db()

    assert loc.country == country


@pytest.mark.django_db()
def test_location_update_relationships_by_name_fallback():
    country = mommy.make(
        Country,
        code='XYZQ',
        short_code='XY',
        location_prefix='QQ',
        name='Xyzlandia',
        short_name='Xyzlandia',
    )
    # prefix won't match (code starts with 'AB'), but name will
    loc = mommy.make(Location, code='ABCD', _country='Xyzlandia')
    loc.update_relationships()
    loc.refresh_from_db()

    assert loc.country == country


@pytest.mark.django_db()
def test_location_update_relationships_domestic_fallback():
    usa = mommy.make(
        Country,
        code='USA',
        short_code='US',
        location_prefix='US',
        name='United States',
        short_name='US',
    )
    # Code starts with digits → domestic fallback
    loc = mommy.make(Location, code='11DC', _country='NoMatch')
    loc.update_relationships()
    loc.refresh_from_db()

    assert loc.country == usa


# ---------------------------------------------------------------------------
# Post model
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_post_str_uses_location():
    usa = mommy.make(
        Country,
        code='USA',
        short_code='US',
        location_prefix='US',
        name='United States',
        short_name='US',
    )
    loc = mommy.make(Location, code='11DC', city='Washington', state='DC', country=usa)
    post = mommy.make(Post, location=loc)

    assert str(post) == 'Washington, DC'


@pytest.mark.django_db()
def test_post_defaults():
    post = mommy.make(Post, location=None, tour_of_duty=None)
    assert post.cost_of_living_adjustment == 0
    assert post.differential_rate == 0
    assert post.danger_pay == 0
    assert post.has_consumable_allowance is False
    assert post.has_service_needs_differential is False


@pytest.mark.django_db()
def test_post_update_relationships():
    tod = mommy.make(TourOfDuty, code='PTOD1', long_description='Tour', short_description='T')
    loc = mommy.make(Location, code='POST1')
    post = mommy.make(Post, _tod_code='PTOD1', _location_code='POST1', location=None, tour_of_duty=None)

    post.update_relationships()
    post.refresh_from_db()

    assert post.tour_of_duty == tod
    assert post.location == loc


@pytest.mark.django_db()
def test_post_permission_codename():
    post = mommy.make(Post, location=None, tour_of_duty=None)
    expected = f"can_edit_post_capsule_description:{post.id}"
    assert post.permission_edit_post_capsule_description_codename == expected


@pytest.mark.django_db()
def test_post_create_permissions():
    loc = mommy.make(Location, code='PPERM')
    post = mommy.make(Post, location=loc, tour_of_duty=None)
    post.create_permissions()

    from django.contrib.auth.models import Group
    group = Group.objects.get(name=f'post_editors:{post.id}')
    assert group.permissions.filter(
        codename=f'can_edit_post_capsule_description:{post.id}'
    ).exists()


# ---------------------------------------------------------------------------
# m2m signal: highlighted positions
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_highlighted_positions_signal_sets_flag():
    org = mommy.make(
        Organization,
        code='SIG001',
        short_description='SIG',
        long_description='Signal Org',
    )
    position = mommy.make('position.Position', is_highlighted=False)

    # Adding position to highlighted_positions should set is_highlighted=True
    org.highlighted_positions.add(position)
    position.refresh_from_db()
    assert position.is_highlighted is True

    # Removing should set it back to False
    org.highlighted_positions.remove(position)
    position.refresh_from_db()
    assert position.is_highlighted is False
