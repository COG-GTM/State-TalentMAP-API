"""
Unit tests for talentmap_api.integrations.synchronization_helpers

Covers:
  - get_soap_client in test mode (mock client reads from test_data XML files)
  - get_soap_client with certificate/non-test path (mocked zeep)
  - generate_soap_header
  - All mode_* data transformation functions (return values + callable tag_map entries)
  - get_synchronization_information / MODEL_HELPER_MAP
  - Pagination handling via PaginationStartKey in test-mode SOAP responses
  - Error handling when SOAP XML files are missing
  - post_load_function and override_loading_method callbacks
"""

import os

import pytest
from unittest import mock

import defusedxml.lxml as ET

from django.conf import settings

from talentmap_api.integrations.synchronization_helpers import (
    get_soap_client,
    generate_soap_header,
    get_synchronization_information,
    mode_skills,
    mode_grade,
    mode_tods,
    mode_organizations,
    mode_languages,
    mode_countries,
    mode_locations,
    mode_posts,
    mode_capsule_descriptions,
    mode_positions,
    mode_skill_cones,
    mode_cycles,
    mode_cycle_positions,
    MODEL_HELPER_MAP,
)


# ---------------------------------------------------------------------------
# get_soap_client — test mode
# ---------------------------------------------------------------------------

class TestGetSoapClientTestMode:

    def test_returns_mock_client_object(self):
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        assert client is not None
        assert hasattr(client, 'service')

    def test_service_has_bound_function(self):
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        assert hasattr(client.service, 'IPMSDataWebService')
        assert callable(client.service.IPMSDataWebService)

    def test_reads_xml_from_test_data_for_request_name(self):
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        result = client.service.IPMSDataWebService(RequestName="skill")
        xml_string = ET.tostring(result, encoding="unicode")
        assert "skill" in xml_string
        assert "Executive" in xml_string

    def test_reads_empty_xml_when_pagination_start_key_provided(self):
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        result = client.service.IPMSDataWebService(
            RequestName="skill",
            PaginationStartKey="100"
        )
        xml_string = ET.tostring(result, encoding="unicode")
        # The empty.xml has an empty result set
        assert "IPMSDataWebServiceResult" in xml_string

    def test_reads_correct_xml_file_for_different_request_names(self):
        """Each RequestName maps to a different test XML file."""
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        for request_name in ["grade", "language", "country", "tods"]:
            result = client.service.IPMSDataWebService(RequestName=request_name)
            xml_string = ET.tostring(result, encoding="unicode")
            assert len(xml_string) > 0

    def test_empty_pagination_key_uses_named_file(self):
        """PaginationStartKey='' should behave like no key (use named file)."""
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        result = client.service.IPMSDataWebService(
            RequestName="grade",
            PaginationStartKey=""
        )
        xml_string = ET.tostring(result, encoding="unicode")
        assert "grade" in xml_string

    def test_missing_request_name_file_raises(self):
        """Requesting a non-existent XML file should raise an error."""
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        with pytest.raises(Exception):
            client.service.IPMSDataWebService(RequestName="nonexistent_data_file")

    def test_different_soap_function_names_bind_correctly(self):
        """The soap_function name becomes the method name on client.service."""
        client = get_soap_client(soap_function="CustomFunction", test=True)
        assert hasattr(client.service, 'CustomFunction')
        assert callable(client.service.CustomFunction)
        # Original function name should NOT be present
        assert not hasattr(client.service, 'IPMSDataWebService')


# ---------------------------------------------------------------------------
# get_soap_client — non-test mode (mocked zeep)
# ---------------------------------------------------------------------------

class TestGetSoapClientNonTestMode:

    @mock.patch.dict(os.environ, {
        'DJANGO_WSDL_SSL_CERT': '/fake/cert.pem',
        'DJANGO_WSDL_LOCATION': 'http://fake.wsdl/service?wsdl',
    })
    @mock.patch('talentmap_api.integrations.synchronization_helpers.zeep.Client')
    @mock.patch('talentmap_api.integrations.synchronization_helpers.Transport')
    def test_creates_real_client_with_cert(self, mock_transport, mock_zeep_client):
        mock_zeep_client.return_value = mock.MagicMock()
        mock_zeep_client.return_value.wsdl.types.prefix_map = {}
        result = get_soap_client(test=False)
        mock_zeep_client.assert_called_once()
        assert result is not None

    @mock.patch.dict(os.environ, {
        'DJANGO_WSDL_LOCATION': 'http://fake.wsdl/service?wsdl',
    }, clear=False)
    @mock.patch('talentmap_api.integrations.synchronization_helpers.zeep.Client')
    @mock.patch('talentmap_api.integrations.synchronization_helpers.Transport')
    def test_creates_client_without_cert(self, mock_transport, mock_zeep_client):
        mock_zeep_client.return_value = mock.MagicMock()
        mock_zeep_client.return_value.wsdl.types.prefix_map = {}
        # Remove any cert env var
        os.environ.pop('DJANGO_WSDL_SSL_CERT', None)
        client = get_soap_client(test=False)
        assert client is not None

    @mock.patch.dict(os.environ, {
        'DJANGO_WSDL_LOCATION': 'http://fake.wsdl/service?wsdl',
        'DJANGO_SYNCHRONIZATION_HEADER_1': 'X-Custom=value1',
    }, clear=False)
    @mock.patch('talentmap_api.integrations.synchronization_helpers.zeep.Client')
    @mock.patch('talentmap_api.integrations.synchronization_helpers.Transport')
    def test_parses_synchronization_headers(self, mock_transport, mock_zeep_client):
        mock_zeep_client.return_value = mock.MagicMock()
        mock_zeep_client.return_value.wsdl.types.prefix_map = {}
        os.environ.pop('DJANGO_WSDL_SSL_CERT', None)
        client = get_soap_client(test=False)
        assert client is not None

    @mock.patch.dict(os.environ, {
        'DJANGO_WSDL_LOCATION': 'http://fake.wsdl/service?wsdl',
        'DJANGO_SOAP_NS_OVERRIDE_1': 'ns0=custom_ns',
    }, clear=False)
    @mock.patch('talentmap_api.integrations.synchronization_helpers.zeep.Client')
    @mock.patch('talentmap_api.integrations.synchronization_helpers.Transport')
    def test_applies_namespace_overrides(self, mock_transport, mock_zeep_client):
        mock_client = mock.MagicMock()
        mock_client.wsdl.types.prefix_map = {'ns0': 'http://original.ns'}
        mock_zeep_client.return_value = mock_client
        os.environ.pop('DJANGO_WSDL_SSL_CERT', None)
        get_soap_client(test=False)
        mock_client.set_ns_prefix.assert_called_once_with(
            'custom_ns', 'http://original.ns'
        )


# ---------------------------------------------------------------------------
# generate_soap_header
# ---------------------------------------------------------------------------

class TestGenerateSoapHeader:

    def test_returns_xsd_element(self):
        import zeep
        element = generate_soap_header("TestHeader")
        assert isinstance(element, zeep.xsd.Element)

    def test_tag_name_matches(self):
        element = generate_soap_header("MyTag")
        assert element.qname.localname == "MyTag"


# ---------------------------------------------------------------------------
# mode_* return value structure tests
# ---------------------------------------------------------------------------

ALL_SIMPLE_MODES = [
    ("mode_skills", mode_skills),
    ("mode_grade", mode_grade),
    ("mode_tods", mode_tods),
    ("mode_organizations", mode_organizations),
    ("mode_languages", mode_languages),
    ("mode_countries", mode_countries),
    ("mode_locations", mode_locations),
    ("mode_posts", mode_posts),
    ("mode_capsule_descriptions", mode_capsule_descriptions),
    ("mode_positions", mode_positions),
    ("mode_skill_cones", mode_skill_cones),
    ("mode_cycles", mode_cycles),
    ("mode_cycle_positions", mode_cycle_positions),
]


class TestModeReturnStructure:

    @pytest.mark.parametrize("name,mode_fn", ALL_SIMPLE_MODES)
    def test_returns_six_element_tuple(self, name, mode_fn):
        result = mode_fn()
        assert isinstance(result, tuple), f"{name} should return a tuple"
        assert len(result) == 6, f"{name} should return a 6-element tuple"

    @pytest.mark.parametrize("name,mode_fn", ALL_SIMPLE_MODES)
    def test_soap_arguments_has_required_keys(self, name, mode_fn):
        soap_arguments, *_ = mode_fn()
        for key in ("RequestorID", "Action", "RequestName",
                    "MaximumOutputRows", "Version", "DataFormat",
                    "InputParameters"):
            assert key in soap_arguments, f"{name}: missing key '{key}' in soap_arguments"
        assert soap_arguments["RequestorID"] == "TalentMAP"
        assert soap_arguments["Action"] == "GET"
        assert soap_arguments["DataFormat"] == "XML"

    @pytest.mark.parametrize("name,mode_fn", ALL_SIMPLE_MODES)
    def test_instance_tag_is_nonempty_string(self, name, mode_fn):
        _, instance_tag, *_ = mode_fn()
        assert isinstance(instance_tag, str) and len(instance_tag) > 0

    @pytest.mark.parametrize("name,mode_fn", ALL_SIMPLE_MODES)
    def test_tag_map_is_dict(self, name, mode_fn):
        _, _, tag_map, *_ = mode_fn()
        assert isinstance(tag_map, dict)

    @pytest.mark.parametrize("name,mode_fn", ALL_SIMPLE_MODES)
    def test_collision_field_is_string(self, name, mode_fn):
        _, _, _, collision_field, *_ = mode_fn()
        assert isinstance(collision_field, str) and len(collision_field) > 0


# ---------------------------------------------------------------------------
# mode_skills specifics
# ---------------------------------------------------------------------------

class TestModeSkills:

    def test_request_name_is_skill(self):
        soap_args, instance_tag, tag_map, collision_field, post_load, override = mode_skills()
        assert soap_args["RequestName"] == "skill"
        assert instance_tag == "skill"
        assert collision_field == "code"
        assert "code" in tag_map
        assert "description" in tag_map
        assert post_load is None
        assert override is None

    def test_tag_map_values_are_simple_strings(self):
        _, _, tag_map, *_ = mode_skills()
        for v in tag_map.values():
            assert isinstance(v, str)


# ---------------------------------------------------------------------------
# mode_grade specifics
# ---------------------------------------------------------------------------

class TestModeGrade:

    def test_request_name_is_grade(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_grade()
        assert soap_args["RequestName"] == "grade"
        assert instance_tag == "grade"
        assert collision_field == "code"
        assert tag_map == {"code": "code"}


# ---------------------------------------------------------------------------
# mode_tods specifics (has callable tag_map entries)
# ---------------------------------------------------------------------------

class TestModeTods:

    def test_request_name_is_tods(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_tods()
        assert soap_args["RequestName"] == "tods"
        assert instance_tag == "tod"

    def test_tag_map_has_callable_entries(self):
        _, _, tag_map, *_ = mode_tods()
        assert callable(tag_map["long_description"])
        assert callable(tag_map["is_active"])

    def test_long_description_callable_strips_and_replaces_amp(self):
        _, _, tag_map, *_ = mode_tods()
        long_desc_fn = tag_map["long_description"]
        mock_instance = mock.MagicMock()
        mock_item = mock.MagicMock()
        mock_item.text = "2 YRS (1 R &amp; R )"
        long_desc_fn(mock_instance, mock_item)
        assert mock_instance.long_description == "2 YRS (1 R & R )"

    def test_is_active_callable_with_truthy_value(self):
        _, _, tag_map, *_ = mode_tods()
        is_active_fn = tag_map["is_active"]
        mock_instance = mock.MagicMock()
        mock_item = mock.MagicMock()
        mock_item.text = "1"
        is_active_fn(mock_instance, mock_item)
        assert mock_instance.is_active is True

    def test_is_active_callable_with_falsy_value(self):
        _, _, tag_map, *_ = mode_tods()
        is_active_fn = tag_map["is_active"]
        mock_instance = mock.MagicMock()
        mock_item = mock.MagicMock()
        mock_item.text = "0"
        is_active_fn(mock_instance, mock_item)
        assert mock_instance.is_active is False


# ---------------------------------------------------------------------------
# mode_organizations
# ---------------------------------------------------------------------------

class TestModeOrganizations:

    def test_request_name_is_organization(self):
        soap_args, instance_tag, tag_map, *_ = mode_organizations()
        assert soap_args["RequestName"] == "organization"
        assert instance_tag == "organization"
        assert "is_bureau" in tag_map
        assert callable(tag_map["is_bureau"])
        assert callable(tag_map["is_regional"])


# ---------------------------------------------------------------------------
# mode_languages (has post_load_function)
# ---------------------------------------------------------------------------

class TestModeLanguages:

    def test_request_name_is_language(self):
        soap_args, instance_tag, tag_map, collision_field, post_load, override = mode_languages()
        assert soap_args["RequestName"] == "language"
        assert instance_tag == "language"
        assert collision_field == "code"
        assert post_load is not None
        assert callable(post_load)
        assert override is None

    @mock.patch('talentmap_api.integrations.synchronization_helpers.Proficiency')
    def test_post_load_function_calls_create_defaults(self, mock_proficiency):
        _, _, _, _, post_load, _ = mode_languages()
        post_load(mock.MagicMock(), [], [])
        mock_proficiency.create_defaults.assert_called_once()


# ---------------------------------------------------------------------------
# mode_countries
# ---------------------------------------------------------------------------

class TestModeCountries:

    def test_request_name_is_country(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_countries()
        assert soap_args["RequestName"] == "country"
        assert instance_tag == "country"
        assert collision_field == "code"
        assert "name" in tag_map
        assert "short_name" in tag_map
        assert "short_code" in tag_map
        assert "location_prefix" in tag_map


# ---------------------------------------------------------------------------
# mode_locations
# ---------------------------------------------------------------------------

class TestModeLocations:

    def test_request_name_is_location(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_locations()
        assert soap_args["RequestName"] == "location"
        assert instance_tag == "location"
        assert "city" in tag_map
        assert "state" in tag_map
        assert "country" in tag_map


# ---------------------------------------------------------------------------
# mode_posts (has callable entries via set_foreign_key_by_filters)
# ---------------------------------------------------------------------------

class TestModePosts:

    def test_request_name_is_orgpost(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_posts()
        assert soap_args["RequestName"] == "orgpost"
        assert instance_tag == "orgpost"
        assert collision_field == "_location_code"
        assert callable(tag_map["tod_code"])
        assert callable(tag_map["has_consumable_allowance"])
        assert callable(tag_map["has_service_needs_differential"])


# ---------------------------------------------------------------------------
# mode_capsule_descriptions (supports last_updated_date)
# ---------------------------------------------------------------------------

class TestModeCapsuleDescriptions:

    def test_request_name_is_positioncapsule(self):
        soap_args, *_ = mode_capsule_descriptions()
        assert soap_args["RequestName"] == "positioncapsule"

    def test_without_last_updated_date(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_capsule_descriptions()
        assert "LAST_DATE_UPDATED" not in soap_args["InputParameters"]
        assert instance_tag == "positionCapsule"
        assert collision_field == "_pos_seq_num"

    def test_with_last_updated_date(self):
        soap_args, *_ = mode_capsule_descriptions(last_updated_date="2023/01/01 00:00:00")
        assert "LAST_DATE_UPDATED" in soap_args["InputParameters"]
        assert "2023/01/01 00:00:00" in soap_args["InputParameters"]

    def test_tag_map_has_date_callables(self):
        _, _, tag_map, *_ = mode_capsule_descriptions()
        assert callable(tag_map["DATE_CREATED"])
        assert callable(tag_map["DATE_UPDATED"])


# ---------------------------------------------------------------------------
# mode_positions (has post_load_function, supports last_updated_date)
# ---------------------------------------------------------------------------

class TestModePositions:

    def test_request_name_is_position(self):
        soap_args, instance_tag, tag_map, collision_field, post_load, override = mode_positions()
        assert soap_args["RequestName"] == "position"
        assert instance_tag == "position"
        assert collision_field == "_seq_num"
        assert post_load is not None
        assert callable(post_load)
        assert override is None

    def test_with_last_updated_date(self):
        soap_args, *_ = mode_positions(last_updated_date="2023/06/15 12:00:00")
        assert "LAST_DATE_UPDATED" in soap_args["InputParameters"]
        assert "2023/06/15 12:00:00" in soap_args["InputParameters"]

    def test_without_last_updated_date(self):
        soap_args, *_ = mode_positions()
        assert "LAST_DATE_UPDATED" not in soap_args["InputParameters"]

    def test_tag_map_has_callable_entries(self):
        _, _, tag_map, *_ = mode_positions()
        assert callable(tag_map["is_overseas"])
        assert callable(tag_map["tod_code"])
        assert callable(tag_map["create_date"])
        assert callable(tag_map["update_date"])
        assert callable(tag_map["effective_date"])

    @mock.patch('talentmap_api.integrations.synchronization_helpers.SavedSearch')
    def test_post_load_with_new_ids(self, mock_saved_search):
        _, _, _, _, post_load, _ = mode_positions()
        post_load(mock.MagicMock(), [1, 2, 3], [])
        mock_saved_search.update_counts_for_endpoint.assert_called_once_with(
            endpoint='position', contains=True
        )

    @mock.patch('talentmap_api.integrations.synchronization_helpers.SavedSearch')
    def test_post_load_with_no_changes(self, mock_saved_search):
        _, _, _, _, post_load, _ = mode_positions()
        post_load(mock.MagicMock(), [], [])
        mock_saved_search.update_counts_for_endpoint.assert_not_called()


# ---------------------------------------------------------------------------
# mode_skill_cones (has get_nested_tag callable)
# ---------------------------------------------------------------------------

class TestModeSkillCones:

    def test_request_name_is_jobcategoryskill(self):
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_skill_cones()
        assert soap_args["RequestName"] == "jobcategoryskill"
        assert instance_tag == "jobCategory"
        assert collision_field == "_id"
        assert callable(tag_map["skills"])


# ---------------------------------------------------------------------------
# mode_cycles (has override_loading_method)
# ---------------------------------------------------------------------------

class TestModeCycles:

    def test_request_name_is_cycle(self):
        soap_args, instance_tag, tag_map, collision_field, post_load, override = mode_cycles()
        assert soap_args["RequestName"] == "cycle"
        assert instance_tag == "cycle"
        assert collision_field == "_id"
        assert post_load is None
        assert override is not None
        assert callable(override)

    def test_tag_map_keys(self):
        _, _, tag_map, *_ = mode_cycles()
        assert "id" in tag_map
        assert "name" in tag_map
        assert "category_code" in tag_map
        assert "status" in tag_map


# ---------------------------------------------------------------------------
# mode_cycle_positions (has override_loading_method + post_load_function,
#   supports last_updated_date)
# ---------------------------------------------------------------------------

class TestModeCyclePositions:

    def test_request_name_is_availableposition(self):
        soap_args, instance_tag, tag_map, collision_field, post_load, override = mode_cycle_positions()
        assert soap_args["RequestName"] == "availableposition"
        assert instance_tag == "availablePosition"
        assert collision_field == "_cp_id"
        assert post_load is not None
        assert callable(post_load)
        assert override is not None
        assert callable(override)

    def test_tag_map_is_empty(self):
        """mode_cycle_positions uses override_loading_method instead of tag_map."""
        _, _, tag_map, *_ = mode_cycle_positions()
        assert tag_map == {}

    def test_with_last_updated_date(self):
        soap_args, *_ = mode_cycle_positions(last_updated_date="2023/01/01 00:00:00")
        assert "LAST_DATE_UPDATED" in soap_args["InputParameters"]

    def test_without_last_updated_date(self):
        soap_args, *_ = mode_cycle_positions()
        assert "LAST_DATE_UPDATED" not in soap_args["InputParameters"]

    @mock.patch('talentmap_api.integrations.synchronization_helpers.SavedSearch')
    def test_post_load_with_updated_ids(self, mock_saved_search):
        _, _, _, _, post_load, _ = mode_cycle_positions()
        post_load(mock.MagicMock(), [], [10, 20])
        mock_saved_search.update_counts_for_endpoint.assert_called_once_with(
            endpoint='cycleposition', contains=True
        )

    @mock.patch('talentmap_api.integrations.synchronization_helpers.SavedSearch')
    def test_post_load_with_no_changes(self, mock_saved_search):
        _, _, _, _, post_load, _ = mode_cycle_positions()
        post_load(mock.MagicMock(), [], [])
        mock_saved_search.update_counts_for_endpoint.assert_not_called()


# ---------------------------------------------------------------------------
# get_synchronization_information / MODEL_HELPER_MAP
# ---------------------------------------------------------------------------

class TestGetSynchronizationInformation:

    def test_returns_iterator_for_known_model(self):
        result = get_synchronization_information("position.Skill")
        tasks = list(result)
        assert len(tasks) == 1
        assert tasks[0] is mode_skills

    def test_raises_key_error_for_unknown_model(self):
        with pytest.raises(KeyError):
            get_synchronization_information("nonexistent.Model")

    def test_all_models_in_map(self):
        expected_models = [
            "position.Skill", "position.SkillCone", "position.Grade",
            "position.CapsuleDescription", "organization.TourOfDuty",
            "organization.Organization", "organization.Country",
            "organization.Location", "organization.Post",
            "language.Language", "position.Position",
            "bidding.BidCycle", "bidding.CyclePosition",
        ]
        for model_key in expected_models:
            assert model_key in MODEL_HELPER_MAP
            tasks = list(get_synchronization_information(model_key))
            assert len(tasks) >= 1
            assert callable(tasks[0])


# ---------------------------------------------------------------------------
# Pagination behaviour via test-mode SOAP client
# ---------------------------------------------------------------------------

class TestPaginationBehavior:

    def test_cycle_xml_contains_pagination_start_keys(self):
        """The cycle.xml test data file contains paginationStartKey elements."""
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        result = client.service.IPMSDataWebService(RequestName="cycle")
        xml_string = ET.tostring(result, encoding="unicode")
        assert "paginationStartKey" in xml_string

    def test_second_page_request_returns_empty(self):
        """Requesting with PaginationStartKey returns empty.xml (no more data)."""
        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        result = client.service.IPMSDataWebService(
            RequestName="cycle",
            PaginationStartKey="5"
        )
        xml_string = ET.tostring(result, encoding="unicode")
        # empty.xml has no cycle elements
        assert "cycle" not in xml_string or "<cycles" not in xml_string


# ---------------------------------------------------------------------------
# Integration-style: test-mode client with XMLloader
# ---------------------------------------------------------------------------

class TestSoapClientWithXMLLoader:

    def test_skill_data_parses_through_loader(self):
        """Verify the full path: get_soap_client → call → XMLloader."""
        from talentmap_api.common.xml_helpers import XMLloader
        from talentmap_api.position.models import Skill

        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_skills()
        response_xml = ET.tostring(
            client.service.IPMSDataWebService(**soap_args),
            encoding="unicode"
        )
        assert response_xml is not None
        assert len(response_xml) > 0
        # Verify loader can be initialized with the mode's return values
        XMLloader(Skill, instance_tag, tag_map, 'update', collision_field)

    def test_grade_data_parses_through_loader(self):
        from talentmap_api.common.xml_helpers import XMLloader
        from talentmap_api.position.models import Grade

        client = get_soap_client(soap_function="IPMSDataWebService", test=True)
        soap_args, instance_tag, tag_map, collision_field, _, _ = mode_grade()
        response_xml = ET.tostring(
            client.service.IPMSDataWebService(**soap_args),
            encoding="unicode"
        )
        assert response_xml is not None
        assert "grade" in response_xml
        XMLloader(Grade, instance_tag, tag_map, 'update', collision_field)


# ---------------------------------------------------------------------------
# Test data file existence
# ---------------------------------------------------------------------------

class TestTestDataFiles:

    EXPECTED_FILES = [
        "skill.xml", "grade.xml", "tods.xml", "organization.xml",
        "language.xml", "country.xml", "location.xml", "orgpost.xml",
        "positioncapsule.xml", "position.xml", "jobcategoryskill.xml",
        "cycle.xml", "availableposition.xml", "empty.xml",
        "jobcategory.xml",
    ]

    @pytest.mark.parametrize("filename", EXPECTED_FILES)
    def test_test_data_file_exists(self, filename):
        filepath = os.path.join(
            settings.BASE_DIR,
            'talentmap_api', 'data', 'test_data', 'soap_integration',
            filename
        )
        assert os.path.isfile(filepath), f"Missing test data file: {filename}"

    @pytest.mark.parametrize("filename", EXPECTED_FILES)
    def test_test_data_file_is_valid_xml(self, filename):
        filepath = os.path.join(
            settings.BASE_DIR,
            'talentmap_api', 'data', 'test_data', 'soap_integration',
            filename
        )
        parser = ET._etree.XMLParser(recover=True)
        tree = ET.parse(filepath, parser)
        assert tree.getroot() is not None


# ---------------------------------------------------------------------------
# MODEL_HELPER_MAP completeness
# ---------------------------------------------------------------------------

class TestModelHelperMap:

    def test_map_has_expected_length(self):
        assert len(MODEL_HELPER_MAP) == 13

    def test_each_value_is_list_of_callables(self):
        for model_key, helpers in MODEL_HELPER_MAP.items():
            assert isinstance(helpers, list), f"{model_key}: value should be a list"
            for helper in helpers:
                assert callable(helper), f"{model_key}: {helper} should be callable"

    def test_request_names_match_test_data_files(self):
        """Each mode function's RequestName should have a corresponding test data file."""
        for model_key, helpers in MODEL_HELPER_MAP.items():
            for helper in helpers:
                soap_args, *_ = helper()
                request_name = soap_args["RequestName"]
                filepath = os.path.join(
                    settings.BASE_DIR,
                    'talentmap_api', 'data', 'test_data', 'soap_integration',
                    f'{request_name}.xml'
                )
                assert os.path.isfile(filepath), (
                    f"{model_key} → {helper.__name__}: no test data for "
                    f"RequestName='{request_name}'"
                )
