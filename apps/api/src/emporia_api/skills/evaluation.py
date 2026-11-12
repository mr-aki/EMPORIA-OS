"""Deterministic, offline contract checks for advisory skill outputs.

This evaluator measures required-section coverage and non-empty section bodies only.
It deliberately does not claim to judge factual accuracy, reasoning quality, or
business suitability.
"""
from __future__ import annotations

import re
from typing import Any

from emporia_api.skills.registry import SkillDefinition

_HEADING_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
_MARKDOWN_BOLD = re.compile(r"^\*\*(.+?)\*\*:?\s*$")


def _normalise_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _heading_from_line(line: str) -> str | None:
    candidate = line.strip()
    bold = _MARKDOWN_BOLD.match(candidate)
    if bold:
        candidate = bold.group(1)
    elif _HEADING_PREFIX.match(candidate):
        candidate = _HEADING_PREFIX.sub("", candidate, count=1).strip()
    else:
        return None
    candidate = candidate.rstrip(":").strip()
    return _normalise_heading(candidate) if candidate else None


def _extract_sections(output: str) -> dict[str, bool]:
    """Map normalized headings to whether their section contains non-whitespace text."""
    sections: dict[str, bool] = {}
    active_heading: str | None = None

    for line in output.splitlines():
        heading = _heading_from_line(line)
        if heading is not None:
            active_heading = heading
            sections.setdefault(heading, False)
        elif active_heading is not None and line.strip():
            sections[active_heading] = True

    return sections


def evaluate_skill_output(skill: SkillDefinition, output: str) -> dict[str, Any]:
    """Check that every contract section is a standalone heading with a non-empty body."""
    sections = _extract_sections(output) if isinstance(output, str) else {}
    present: list[str] = []
    missing: list[str] = []
    empty: list[str] = []

    for section in skill.output_sections:
        normalized = _normalise_heading(section)
        if normalized not in sections:
            missing.append(section)
        elif not sections[normalized]:
            empty.append(section)
        else:
            present.append(section)

    return {
        "evaluation_type": "required_section_coverage",
        "skill_id": skill.id,
        "skill_version": skill.version,
        "passed": (
            isinstance(output, str)
            and bool(output.strip())
            and not missing
            and not empty
        ),
        "evaluated_sections": len(skill.output_sections),
        "present_sections": present,
        "missing_sections": missing,
        "empty_sections": empty,
        "limitations": [
            "Checks section headings and non-empty bodies only; it does not verify factual accuracy or calculations.",
            "Does not assess reasoning quality, evidence quality, or recommendation safety.",
        ],
    }
