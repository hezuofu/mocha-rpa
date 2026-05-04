"""Tests for pipeline validator."""

import pytest
from mocharpa.pipeline.validator import validate_pipeline


class TestValidatePipeline:
    def test_empty_dict(self):
        errors = validate_pipeline({})
        assert len(errors) > 0

    def test_minimal_valid(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{"name": "s1", "action": "find_click", "locator": "name:OK"}],
            }
        })
        assert errors == []

    def test_missing_action(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{"name": "s1"}],
            }
        })
        assert any("action" in e.lower() for e in errors)

    def test_unknown_action(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{"name": "s1", "action": "nonexistent"}],
            }
        })
        assert any("unknown" in e.lower() for e in errors)

    def test_missing_required_param(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{"name": "s1", "action": "http_get"}],
            }
        })
        assert any("url" in e for e in errors)

    def test_locator_string_valid(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{"name": "s1", "action": "find_click", "locator": "name:OK"}],
            }
        })
        assert errors == []

    def test_locator_string_invalid_type(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{"name": "s1", "action": "find_click", "locator": "badtype:OK"}],
            }
        })
        assert any("unknown" in e.lower() for e in errors)

    def test_condition_nested_and(self):
        errors = validate_pipeline({
            "pipeline": {
                "name": "test",
                "steps": [{
                    "name": "s1",
                    "action": "transform",
                    "fn": "identity",
                    "condition": {"and": [True, {"eq": ["${data.x}", "ok"]}]},
                }],
            }
        })
        assert errors == []

    def test_bare_list_of_steps(self):
        errors = validate_pipeline([
            {"name": "s1", "action": "transform", "fn": "identity"},
        ])
        assert errors == []
