import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.api_mock.services.api_mock.path_matcher import (
    _body_subset_match,
    _count_leaf_constraints,
    _match_path_template,
    _normalize_path,
    _normalize_path_for_compare,
)
from app.domains.api_mock.services.api_mock.preview_service import _case_matchers_satisfied
from app.domains.api_mock.models.api_mock import SddApiMockRule


class ApiMockPathMatcherTest(unittest.TestCase):
    def test_normalize_path(self):
        self.assertEqual(_normalize_path("/api/v1/users"), "/api/v1/users")
        self.assertEqual(_normalize_path("api/v1/users/"), "/api/v1/users/")
        self.assertEqual(_normalize_path(""), "/")
        self.assertEqual(_normalize_path("   "), "/")

    def test_normalize_path_for_compare(self):
        self.assertEqual(_normalize_path_for_compare("/api/v1/users/"), "/api/v1/users")
        self.assertEqual(_normalize_path_for_compare("api/v1/users"), "/api/v1/users")
        self.assertEqual(_normalize_path_for_compare(""), "/")

    def test_match_path_template(self):
        # Exact match
        self.assertEqual(_match_path_template("/api/users", "/api/users"), {})
        self.assertIsNone(_match_path_template("/api/users", "/api/admins"))

        # Parameter match
        self.assertEqual(_match_path_template("/api/users/{id}", "/api/users/123"), {"id": "123"})
        self.assertEqual(
            _match_path_template("/api/{type}/{id}/roles", "/api/users/45/roles"),
            {"type": "users", "id": "45"}
        )

        # Parameter mismatch
        self.assertIsNone(_match_path_template("/api/users/{id}", "/api/users"))
        self.assertIsNone(_match_path_template("/api/users/{id}", "/api/users/123/profile"))

    def test_body_subset_match(self):
        # Dict
        self.assertTrue(_body_subset_match({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(_body_subset_match({"a": 1}, {"b": 2}))
        self.assertFalse(_body_subset_match({"a": 1}, "not a dict"))

        # Deep dict
        self.assertTrue(_body_subset_match({"nested": {"x": 10}}, {"nested": {"x": 10, "y": 20}}))
        self.assertFalse(_body_subset_match({"nested": {"x": 10}}, {"nested": {"y": 20}}))

        # List
        self.assertTrue(_body_subset_match([1, 2], [1, 2]))
        self.assertFalse(_body_subset_match([1], [1, 2]))
        
        # Deep list of dicts
        self.assertTrue(_body_subset_match([{"a": 1}], [{"a": 1, "b": 2}]))
        self.assertFalse(_body_subset_match([{"a": 1}], [{"a": 2}]))

        # Primitives
        self.assertTrue(_body_subset_match("Hello", "Hello"))
        self.assertFalse(_body_subset_match("Hello", "World"))

    def test_count_leaf_constraints(self):
        self.assertEqual(_count_leaf_constraints(None), 0)
        self.assertEqual(_count_leaf_constraints({}), 0)
        self.assertEqual(_count_leaf_constraints([]), 0)
        self.assertEqual(_count_leaf_constraints("scalar"), 1)
        self.assertEqual(_count_leaf_constraints({"a": 1, "b": 2}), 2)
        self.assertEqual(_count_leaf_constraints({"a": {"c": 3, "d": 4}, "b": 2}), 3)

    def test_case_matchers_satisfied(self):
        rule = SddApiMockRule()
        
        # No constraints
        matched, specificity = _case_matchers_satisfied(
            rule, path_params={}, query=None, body=None
        )
        self.assertFalse(matched)
        self.assertEqual(specificity, 0)
        
        # Path parameter matching
        rule.request_path_params_json = {"id": "123"}
        matched, specificity = _case_matchers_satisfied(
            rule, path_params={"id": "123"}, query=None, body=None
        )
        self.assertTrue(matched)
        self.assertEqual(specificity, 1)

        matched, _ = _case_matchers_satisfied(
            rule, path_params={"id": "456"}, query=None, body=None
        )
        self.assertFalse(matched)
        
        # Query parameter matching
        rule.request_path_params_json = None
        rule.request_query_json = {"page": "1", "sort": "desc"}
        matched, specificity = _case_matchers_satisfied(
            rule, path_params={}, query={"page": "1", "sort": "desc", "per_page": 20}, body=None
        )
        self.assertTrue(matched)
        self.assertEqual(specificity, 2)

        matched, _ = _case_matchers_satisfied(
            rule, path_params={}, query={"page": "2"}, body=None
        )
        self.assertFalse(matched)

        # Body matching
        rule.request_query_json = None
        rule.request_body_json = {"name": "Alice"}
        matched, specificity = _case_matchers_satisfied(
            rule, path_params={}, query=None, body={"name": "Alice", "age": 30}
        )
        self.assertTrue(matched)
        self.assertEqual(specificity, 1)


if __name__ == "__main__":
    unittest.main()
