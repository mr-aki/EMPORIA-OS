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

    output = "\\n\\n".join(f"## {section}\\n   " for section in skill.output_sections)
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
