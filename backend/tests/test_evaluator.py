"""Tests for the alert rule evaluator."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from backend.alert_engine.evaluator import (
    _evaluate_keyword,
    _evaluate_semantic,
    evaluate_rule,
    EvaluationResult,
)
from backend.shared.models import AlertRule, ProcessedDocument, RuleMode, Severity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_doc(**kwargs) -> ProcessedDocument:
    defaults = dict(
        id=uuid4(),
        source_name="test-source",
        title="Test Event",
        content="There has been a critical security vulnerability in the payment module.",
        summary="Security issue found",
        tags=["security", "payment"],
        severity=Severity.high,
    )
    defaults.update(kwargs)
    return ProcessedDocument(**defaults)


def make_rule(**kwargs) -> AlertRule:
    defaults = dict(
        id=uuid4(),
        name="Test Rule",
        mode=RuleMode.keyword,
        is_active=True,
        alert_severity=Severity.medium,
        cooldown_seconds=0,
    )
    defaults.update(kwargs)
    return AlertRule(**defaults)


# ---------------------------------------------------------------------------
# Keyword mode tests
# ---------------------------------------------------------------------------

class TestKeywordEvaluator:
    def test_single_keyword_match_in_content(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=["security"])
        doc = make_doc()
        result = _evaluate_keyword(rule, doc)
        assert result.matched is True
        assert "security" in result.reason.lower()

    def test_keyword_match_in_title(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=["test"])
        doc = make_doc(title="Test Event")
        result = _evaluate_keyword(rule, doc)
        assert result.matched is True

    def test_keyword_match_in_tags(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=["payment"])
        doc = make_doc()
        result = _evaluate_keyword(rule, doc)
        assert result.matched is True

    def test_no_keyword_match(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=["blockchain", "nft"])
        doc = make_doc()
        result = _evaluate_keyword(rule, doc)
        assert result.matched is False

    def test_phrase_match(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=["payment module"])
        doc = make_doc()
        result = _evaluate_keyword(rule, doc)
        assert result.matched is True

    def test_empty_keywords(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=[])
        doc = make_doc()
        result = _evaluate_keyword(rule, doc)
        assert result.matched is False

    def test_case_insensitive(self):
        rule = make_rule(mode=RuleMode.keyword, keywords=["SECURITY"])
        doc = make_doc()
        result = _evaluate_keyword(rule, doc)
        assert result.matched is True


# ---------------------------------------------------------------------------
# Semantic mode tests
# ---------------------------------------------------------------------------

class TestSemanticEvaluator:
    def test_no_reference_text(self):
        rule = make_rule(mode=RuleMode.semantic, reference_text=None, similarity_threshold=0.8)
        doc = make_doc()
        result = _evaluate_semantic(rule, doc)
        assert result.matched is False

    @patch("backend.alert_engine.evaluator.embed_text")
    def test_high_similarity_matches(self, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        rule = make_rule(mode=RuleMode.semantic, reference_text="security", similarity_threshold=0.8)
        doc = make_doc(embedding=[1.0, 0.0, 0.0])
        result = _evaluate_semantic(rule, doc)
        assert result.matched is True
        assert result.score == pytest.approx(1.0, abs=0.01)

    @patch("backend.alert_engine.evaluator.embed_text")
    def test_low_similarity_no_match(self, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        rule = make_rule(mode=RuleMode.semantic, reference_text="weather", similarity_threshold=0.8)
        doc = make_doc(embedding=[0.0, 1.0, 0.0])
        result = _evaluate_semantic(rule, doc)
        assert result.matched is False
        assert result.score == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestRuleFilters:
    def test_source_filter_passes(self):
        src_id = uuid4()
        rule = make_rule(
            mode=RuleMode.keyword,
            keywords=["security"],
            filter_source_ids=[src_id],
        )
        doc = make_doc(source_id=src_id)
        result = evaluate_rule(rule, doc)
        assert result.matched is True

    def test_source_filter_blocks(self):
        rule = make_rule(
            mode=RuleMode.keyword,
            keywords=["security"],
            filter_source_ids=[uuid4()],
        )
        doc = make_doc(source_id=uuid4())
        result = evaluate_rule(rule, doc)
        assert result.matched is False

    def test_severity_filter_passes(self):
        rule = make_rule(
            mode=RuleMode.keyword,
            keywords=["security"],
            filter_severity=[Severity.high, Severity.critical],
        )
        doc = make_doc(severity=Severity.high)
        result = evaluate_rule(rule, doc)
        assert result.matched is True

    def test_severity_filter_blocks(self):
        rule = make_rule(
            mode=RuleMode.keyword,
            keywords=["security"],
            filter_severity=[Severity.critical],
        )
        doc = make_doc(severity=Severity.low)
        result = evaluate_rule(rule, doc)
        assert result.matched is False
