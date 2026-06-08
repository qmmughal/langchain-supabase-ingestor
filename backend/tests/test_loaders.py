"""Tests for REST API loader."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from backend.ingestor.loaders import _extract_items, _stable_id, RestApiLoader
from backend.shared.models import DataSource


class TestExtractItems:
    def test_root_array(self):
        data = [{"id": 1}, {"id": 2}]
        result = _extract_items(data, "$[*]")
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_nested_path(self):
        data = {"results": [{"id": "a"}, {"id": "b"}]}
        result = _extract_items(data, "$.results[*]")
        assert len(result) == 2

    def test_single_object(self):
        data = {"temperature": 22, "wind": 5}
        result = _extract_items(data, "$.current")
        # single object wrapped in list
        # (depends on jmespath returning the dict)
        assert isinstance(result, list)

    def test_empty_response(self):
        result = _extract_items([], "$[*]")
        assert result == []

    def test_nonexistent_path(self):
        result = _extract_items({"foo": "bar"}, "$.nonexistent[*]")
        assert result == []


class TestStableId:
    def test_deterministic(self):
        payload = {"id": "abc", "value": 123}
        assert _stable_id(payload) == _stable_id(payload)

    def test_different_payloads(self):
        a = {"id": "abc"}
        b = {"id": "xyz"}
        assert _stable_id(a) != _stable_id(b)

    def test_length(self):
        assert len(_stable_id({"x": 1})) == 32
