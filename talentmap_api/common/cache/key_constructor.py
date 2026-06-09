import hashlib
import json

from rest_framework_extensions.key_constructor import bits
from rest_framework_extensions.key_constructor.constructors import DefaultKeyConstructor

from talentmap_api.common.common_helpers import order_dict


class PathKeyBit(bits.QueryParamsKeyBit):
    """
    Adds query path as a key bit
    """

    def get_source_dict(self, params, view_instance, view_method, request, args, kwargs):
        return {"path": request.path}


class TalentMAPKeyConstructor(DefaultKeyConstructor):
    """
    Construct the cache key, include query params as a bit
    """
    path_bit = PathKeyBit()
    request_params = bits.QueryParamsKeyBit()

    def prepare_key(self, key_dict):
        # STIG V-220633: Replace MD5 with SHA-256 — MD5 is prohibited by
        # NIST SP 800-131A even for non-cryptographic use in federal systems.
        key_dict = order_dict(key_dict)
        key_dict = json.dumps(key_dict)
        key_hex = hashlib.sha256(key_dict.encode('utf-8')).hexdigest()
        return key_hex


key_func = TalentMAPKeyConstructor()
