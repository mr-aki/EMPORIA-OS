from emporia_api.skills.evaluation import evaluate_skill_output
from emporia_api.skills.registry import SKILLS, get_skill


def test_evaluator_accepts_complete_required_section_headings_for_every_skill():
    for skill in SKILLS:
        output = "\n\n".join(f"## {section}\nEvidence and analysis." for section in skill.output_sections)
        result = evaluate_skill_output(skill, output)

        assert result["passed"] is True, skill.id
        assert result["evaluated_sections"] == len(skill.output_sections)
        assert result["missing_sections"] == []
        assert result["evaluation_type"] == "required_section_coverage"



def test_evaluator_counts_bullet_list_items_as_section_body():
    skill = get_skill("landed-cost-margin-analysis")
    assert skill is not None
    output = "\n\n".join(
        f"## {section}\n- Evidence item one\n- Evidence item two"
        for section in skill.output_sections
    )

    result = evaluate_skill_output(skill, output)

    assert result["passed"] is True
    assert result["empty_sections"] == []
    assert result["missing_sections"] == []

def test_evaluator_reports_missing_sections_without_quality_overclaim():
    skill = get_skill("contribution-margin-waterfall")
    assert skill is not None

    result = evaluate_skill_output(skill, "## Revenue-to-contribution waterfall\nNet sales are shown.")

    assert result["passed"] is False
    assert result["present_sections"] == ["Revenue-to-contribution waterfall"]
    assert len(result["missing_sections"]) == len(skill.output_sections) - 1
    assert any("does not verify factual accuracy" in item for item in result["limitations"])


def test_evaluator_rejects_required_headings_with_empty_bodies():
    skill = get_skill("customer-acquisition-cost-review")
    assert skill is not None

    output = "\n\n".join(f"## {section}\n   " for section in skill.output_sections)
    result = evaluate_skill_output(skill, output)

    assert result["passed"] is False
    assert result["present_sections"] == []
    assert result["missing_sections"] == []
    assert result["empty_sections"] == list(skill.output_sections)


def test_evaluator_does_not_count_section_names_mentioned_only_in_body_text():
    skill = get_skill("customer-acquisition-cost-review")
    assert skill is not None
    output = "This report includes CAC definition and scope, spend component reconciliation, and fully loaded CAC."

    result = evaluate_skill_output(skill, output)

    assert result["passed"] is False
    assert result["present_sections"] == []


def test_evaluator_handles_empty_and_non_string_outputs():
    skill = get_skill("landed-cost-margin-analysis")
    assert skill is not None

    assert evaluate_skill_output(skill, "")["passed"] is False
    assert evaluate_skill_output(skill, None)["passed"] is False


def test_evaluator_ignores_headings_inside_fenced_and_indented_code_blocks():
    skill = get_skill("landed-cost-margin-analysis")
    assert skill is not None
    real_section, *code_only_sections = skill.output_sections
    fence = chr(96) * 4
    nested_fence = chr(96) * 3
    output = "\n".join(
        [
            f"## {real_section}",
            "Evidence is present.",
            f"{fence}markdown",
            f"## {code_only_sections[0]}",
            "Looks complete in a code sample.",
            nested_fence,
            f"## {code_only_sections[1]}",
            "Nested code sample heading.",
            nested_fence,
            fence,
            "~~~markdown",
            f"**{code_only_sections[2]}**:",
            "Looks complete in a tilde code sample.",
            "~~~",
            f"    ## {code_only_sections[3]}",
            "    Indented code body.",
            f"\t**{code_only_sections[4]}**:",
            "\tIndented code body.",
        ]
    )

    result = evaluate_skill_output(skill, output)

    assert result["passed"] is False
    assert result["present_sections"] == [real_section]
    assert result["missing_sections"] == code_only_sections
    assert result["empty_sections"] == []


def test_evaluator_still_accepts_bold_markdown_headings_outside_code_blocks():
    skill = get_skill("landed-cost-margin-analysis")
    assert skill is not None
    output = "\n\n".join(
        f"**{section}**:\nEvidence and analysis."
        for section in skill.output_sections
    )

    result = evaluate_skill_output(skill, output)

    assert result["passed"] is True
    assert result["missing_sections"] == []
    assert result["empty_sections"] == []
