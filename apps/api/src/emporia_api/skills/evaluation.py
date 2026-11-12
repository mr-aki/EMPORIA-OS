"""Deterministic, offline contract checks for advisory skill outputs.

This evaluator measures required-section coverage only. It deliberately does not
claim to judge factual accuracy, reasoning quality, or business suitability.
"""
from __future__ import annotations

import re
from typing import Any

from emporia_api.skills.registry import SkillDefinition

_HEADING_PREFIX = re.compile(r"^\\s*(?:#{1,6}\\s+|[-*+]\\s+|\\d+[.)]\\s+)")
_MARKDOWN_BOLD = re.compile(r"^\\*\\*(.+?)\\*\\*:?\\s*$")


def _normalise_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _extract_headings(output: str) -> set[str]:
    headings: set[str] = set()
    for line in output.splitlines():
        candidate = line.strip()
        bold = _MARKDOWN_BOLD.match(candidate)
        if bold:
            candidate = bold.group(1)
        elif _HEADING_PREFIX.match(candidate):
            candidate = _HEADING_PREFIX.sub("", candidate, count=1).strip()
        else:
            continue
        candidate = candidate.rstrip(":").strip()
        if candidate:
            headings.add(_normalise_heading(candidate))
    return headings


def evaluate_skill_output(skill: SkillDefinition, output: str) -> dict[str, Any]:
    """Check that every contract output section appears as a standalone heading."""
    headings = _extract_headings(output) if isinstance(output, str) else set()
    present: list[str] = []
    missing: list[str] = []
    for section in skill.output_sections:
        if _normalise_heading(section) in headings:
            present.append(section)
        else:
            missing.append(section)
    return {
        "evaluation_type": "required_section_coverage",
        "skill_id": skill.id,
        "skill_version": skill.version,
        "passed": bool(output and output.strip()) and not missing,
        "evaluated_sections": len(skill.output_sections),
        "present_sections": present,
        "missing_sections": missing,
        "limitations": [
            "Checks section headings only; it does not verify factual accuracy or calculations.",
            "Does not assess reasoning quality, evidence quality, or recommendation safety.",
        ],
    }
