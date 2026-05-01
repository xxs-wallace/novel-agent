from __future__ import annotations

from novel_agent.tools.task5_scene_tools import CheckContinuityTool, PlanSceneTool


def test_plan_scene_outputs_scene_plan_structure():
    tool = PlanSceneTool()
    result = tool(
        goal="必须包含：龙尘，青龙\n禁止：穿越\n目标：800字",
        anchor_context="上一段中龙尘刚从战场归来，气氛紧绷。",
        retrieval_json={"sources": [{"path": "analysis/lore.md", "scope": "analysis", "snippet": "神器的来历。"}]},
    )
    assert result["goal"]
    assert result["anchor_context"]
    assert result["must_include"] == ["龙尘", "青龙"]
    assert result["forbidden"] == ["穿越"]
    assert isinstance(result["outline"], list) and len(result["outline"]) >= 3
    assert result["target_word_count"] == 800
    assert isinstance(result["sources"], list) and result["sources"][0]["path"] == "analysis/lore.md"


def test_check_continuity_min_rules_detect_issues():
    plan_tool = PlanSceneTool()
    plan = plan_tool(
        goal="必须包含：龙尘，青龙\n禁止：穿越\n800字",
        anchor_context="锚点：龙尘在城门外停步。",
        retrieval_json=None,
    )

    repeated = "龙尘望着远方，心中翻涌。"
    draft = ("龙尘穿越而来，" + repeated * 30).strip()

    tool = CheckContinuityTool()
    report = tool(draft=draft, scene_plan_json=plan)
    assert isinstance(report["issues"], list)
    types = {i["type"] for i in report["issues"]}
    assert "missing_must_include" in types
    assert "forbidden_present" in types
    assert "word_count_deviation" in types
    assert "high_repetition" in types
