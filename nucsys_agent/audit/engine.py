"""
Audit engine: answers natural-language questions about the engineering models
implemented in nucsys-agent.

The engine uses a two-pass keyword approach:
  1. Phrase matching  — looks for multi-word phrases in the question first.
  2. Token scoring    — counts how many single keyword tokens appear in the question.

A topic is returned when its score exceeds a minimum threshold.  Multiple topics
can be returned when the question spans several areas.  If no topic matches, the
engine returns a list of available topics.
"""
from __future__ import annotations

import re
from typing import Sequence

from .knowledge import TOPICS


# Minimum score (phrase match = 4 pts; single-word match = 1 pt) for a topic
# to appear in the results.  Set to 1 so that a single unambiguous technical
# keyword (e.g. "rankine", "optimizer", "sodium") is sufficient to trigger
# the matching topic.
_MIN_SCORE = 1


def _tokenise(text: str) -> list[str]:
    """Lower-case, strip punctuation, split into words."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _score_topic(question_lower: str, tokens: list[str], topic: dict) -> int:
    """Score a topic against a question using phrase + token matching."""
    score = 0
    for kw in topic["keywords"]:
        kw_lower = kw.lower()
        if " " in kw_lower:
            # Multi-word phrase — worth 4 points
            if kw_lower in question_lower:
                score += 4
        else:
            # Single word — worth 1 point
            if kw_lower in tokens:
                score += 1
    return score


def _format_topic(topic: dict, show_refs: bool = True) -> str:
    """Format a topic entry for terminal display."""
    lines: list[str] = [topic["body"]]

    if show_refs and topic.get("references"):
        lines.append("\nREFERENCES")
        lines.append("──────────")
        for ref in topic["references"]:
            lines.append(f"  · {ref}")

    if topic.get("source_files"):
        lines.append("\nSOURCE CODE")
        lines.append("───────────")
        for sf in topic["source_files"]:
            lines.append(f"  · {sf}")

    return "\n".join(lines)


def _topic_list() -> str:
    lines = [
        "Available topics (ask about any of these):",
        "",
    ]
    for t in TOPICS:
        # Show a short sample of the topic's keywords as hints
        sample = ", ".join(t["keywords"][:4])
        lines.append(f"  • {t['title']:<42}  e.g. \"{sample}\"")
    lines.append(
        "\nType 'back' to return to the main menu, or 'all' to list every topic in full."
    )
    return "\n".join(lines)


class AuditEngine:
    """Answer free-form questions about the engineering models in nucsys-agent."""

    def __init__(self, topics: list[dict] | None = None) -> None:
        self._topics = topics or TOPICS

    # ── public API ──────────────────────────────────────────────────────────

    def ask(self, question: str) -> str:
        """Return a formatted answer for *question*.

        Returns the matching topic body (or bodies), or a list of available
        topics if nothing matches.
        """
        q_lower = question.lower().strip()
        tokens  = _tokenise(q_lower)

        # Special commands ────────────────────────────────────────────────────
        if not q_lower or q_lower in {"help", "?"}:
            return _topic_list()

        if q_lower in {"all", "list all", "show all"}:
            return self._all_topics()

        if q_lower in {"list", "topics", "list topics", "what topics",
                       "what can you explain", "what do you know"}:
            return _topic_list()

        # Score every topic ───────────────────────────────────────────────────
        scored = [
            (t, _score_topic(q_lower, tokens, t))
            for t in self._topics
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Collect results above threshold
        top_score = scored[0][1] if scored else 0
        if top_score < _MIN_SCORE:
            return (
                f"I couldn't find a topic that matches \"{question}\".\n\n"
                + _topic_list()
            )

        # Return all topics whose score is at least half the top score
        # (avoids showing unrelated topics while supporting multi-topic questions)
        cutoff = max(_MIN_SCORE, top_score // 2)
        matches = [t for t, s in scored if s >= cutoff]

        if len(matches) == 1:
            return _format_topic(matches[0])
        else:
            parts = []
            for topic in matches:
                parts.append(_format_topic(topic, show_refs=True))
                parts.append("─" * 62)
            return "\n".join(parts)

    def topic_ids(self) -> list[str]:
        """Return a list of all topic IDs."""
        return [t["id"] for t in self._topics]

    def get_topic(self, topic_id: str) -> str | None:
        """Return the formatted body of a specific topic by ID, or None."""
        for t in self._topics:
            if t["id"] == topic_id:
                return _format_topic(t)
        return None

    # ── private helpers ──────────────────────────────────────────────────────

    def _all_topics(self) -> str:
        sep = "\n" + "═" * 62 + "\n"
        return sep.join(_format_topic(t) for t in self._topics)
