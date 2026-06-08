"""
Alert rule evaluator.

Supports three evaluation modes per rule:
  1. keyword  — fast pattern matching on title/content/tags (no LLM cost)
  2. semantic — cosine similarity between document embedding and a reference text
  3. llm_agent — LangChain agent with tool access decides yes/no

Returns an EvaluationResult for each (rule, document) pair.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from langchain.agents import AgentType, initialize_agent
from langchain.tools import Tool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from backend.shared.models import AlertRule, ProcessedDocument, RuleMode
from backend.shared.ollama_client import embed_text, get_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    matched: bool
    score: float | None = None   # similarity score or None for keyword mode
    mode_used: RuleMode = RuleMode.keyword
    reason: str = ""


# ---------------------------------------------------------------------------
# Mode 1: Keyword matching
# ---------------------------------------------------------------------------

def _evaluate_keyword(rule: AlertRule, doc: ProcessedDocument) -> EvaluationResult:
    """Case-insensitive match of any keyword in title, content, or tags."""
    keywords = [k.strip().lower() for k in rule.keywords if k.strip()]
    if not keywords:
        return EvaluationResult(matched=False, mode_used=RuleMode.keyword, reason="No keywords defined")

    search_corpus = " ".join(
        filter(
            None,
            [
                (doc.title or "").lower(),
                doc.content.lower(),
                " ".join(doc.tags),
            ],
        )
    )

    for kw in keywords:
        # Use word-boundary match for single words, substring match for phrases
        if " " in kw:
            if kw in search_corpus:
                return EvaluationResult(
                    matched=True,
                    mode_used=RuleMode.keyword,
                    reason=f"Phrase match: '{kw}'",
                )
        else:
            pattern = re.compile(r"\b" + re.escape(kw) + r"\b")
            if pattern.search(search_corpus):
                return EvaluationResult(
                    matched=True,
                    mode_used=RuleMode.keyword,
                    reason=f"Keyword match: '{kw}'",
                )

    return EvaluationResult(matched=False, mode_used=RuleMode.keyword, reason="No keywords matched")


# ---------------------------------------------------------------------------
# Mode 2: Semantic similarity
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    av = np.array(a, dtype=np.float32)
    bv = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(av)
    norm_b = np.linalg.norm(bv)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(av, bv) / (norm_a * norm_b))


def _evaluate_semantic(rule: AlertRule, doc: ProcessedDocument) -> EvaluationResult:
    """Embed the reference text and compare against the document embedding."""
    if not rule.reference_text:
        return EvaluationResult(
            matched=False,
            mode_used=RuleMode.semantic,
            reason="No reference text configured",
        )

    doc_embedding = doc.embedding
    if not doc_embedding:
        # Fall back: embed the document content on the fly
        try:
            doc_embedding = embed_text(doc.content[:2000])
        except Exception as exc:
            logger.warning("Could not embed document: %s", exc)
            return EvaluationResult(
                matched=False,
                mode_used=RuleMode.semantic,
                reason=f"Embedding error: {exc}",
            )

    try:
        ref_embedding = embed_text(rule.reference_text)
    except Exception as exc:
        logger.warning("Could not embed reference text: %s", exc)
        return EvaluationResult(
            matched=False,
            mode_used=RuleMode.semantic,
            reason=f"Reference embedding error: {exc}",
        )

    score = _cosine_similarity(ref_embedding, doc_embedding)
    threshold = rule.similarity_threshold or 0.80
    matched = score >= threshold

    return EvaluationResult(
        matched=matched,
        score=round(score, 4),
        mode_used=RuleMode.semantic,
        reason=f"Similarity={score:.4f} (threshold={threshold})",
    )


# ---------------------------------------------------------------------------
# Mode 3: LLM Agent
# ---------------------------------------------------------------------------

_AGENT_SYSTEM = """You are an intelligent alert routing agent.
You will be given an alert rule description and the content of a data event.
Your ONLY job is to decide whether the event matches the rule.

Respond with exactly one word: YES or NO
"""

_AGENT_PROMPT = PromptTemplate.from_template(
    """Alert Rule: {rule_prompt}

Event Title: {title}
Event Content (truncated):
{content}

Does this event match the alert rule? Answer YES or NO only."""
)


def _evaluate_llm_agent(rule: AlertRule, doc: ProcessedDocument) -> EvaluationResult:
    """Use the LLM to decide whether the document matches the rule."""
    if not rule.agent_prompt:
        return EvaluationResult(
            matched=False,
            mode_used=RuleMode.llm_agent,
            reason="No agent_prompt configured",
        )

    try:
        llm = get_llm(temperature=0.0)
        chain = _AGENT_PROMPT | llm | StrOutputParser()
        response = chain.invoke(
            {
                "rule_prompt": rule.agent_prompt,
                "title": doc.title or "(no title)",
                "content": doc.content[:1500],
            }
        )
        answer = response.strip().upper()
        matched = answer.startswith("YES")
        return EvaluationResult(
            matched=matched,
            mode_used=RuleMode.llm_agent,
            reason=f"LLM response: {answer[:20]}",
        )
    except Exception as exc:
        logger.error("LLM agent evaluation failed: %s", exc)
        return EvaluationResult(
            matched=False,
            mode_used=RuleMode.llm_agent,
            reason=f"LLM error: {exc}",
        )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def evaluate_rule(rule: AlertRule, doc: ProcessedDocument) -> EvaluationResult:
    """
    Evaluate a single rule against a document using the rule's configured mode.
    Applies source and severity filters before mode evaluation.
    """
    # --- Pre-filters ---
    if rule.filter_source_ids:
        if doc.source_id not in rule.filter_source_ids:
            return EvaluationResult(
                matched=False, reason="Source filtered out", mode_used=rule.mode
            )

    if rule.filter_severity:
        if doc.severity not in rule.filter_severity:
            return EvaluationResult(
                matched=False, reason="Severity filtered out", mode_used=rule.mode
            )

    # --- Mode evaluation ---
    if rule.mode == RuleMode.keyword:
        return _evaluate_keyword(rule, doc)
    elif rule.mode == RuleMode.semantic:
        return _evaluate_semantic(rule, doc)
    elif rule.mode == RuleMode.llm_agent:
        return _evaluate_llm_agent(rule, doc)
    else:
        return EvaluationResult(
            matched=False, reason=f"Unknown mode: {rule.mode}", mode_used=rule.mode
        )


def evaluate_all_rules(
    rules: list[AlertRule], doc: ProcessedDocument
) -> list[tuple[AlertRule, EvaluationResult]]:
    """Evaluate all rules against a document and return (rule, result) pairs."""
    matches = []
    for rule in rules:
        if not rule.is_active:
            continue
        result = evaluate_rule(rule, doc)
        if result.matched:
            matches.append((rule, result))
            logger.info(
                "Rule '%s' matched document '%s' [%s]",
                rule.name,
                doc.title,
                result.reason,
            )
    return matches
