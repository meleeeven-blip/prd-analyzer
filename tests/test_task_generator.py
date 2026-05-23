"""Unit tests for TaskFormatter."""
from __future__ import annotations

import json

import pytest

from src.models import (
    AnalysisSummary,
    Ambiguity,
    PRDAnalysisResult,
    Requirement,
    RequirementType,
    RiskLevel,
    Task,
)
from src.task_generator import TaskFormatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(tasks: list[Task] | None = None) -> PRDAnalysisResult:
    if tasks is None:
        tasks = [
            Task(
                id="TASK-001",
                title="Implement login endpoint",
                description="POST /auth/login with JWT response",
                acceptance_criteria=["Returns 200 with token on success", "Returns 401 on bad credentials"],
                effort_estimate="1-2 days",
                risk_level=RiskLevel.LOW,
                dependencies=[],
                related_requirements=["REQ-001"],
            ),
            Task(
                id="TASK-002",
                title="Add rate limiting middleware",
                description="Block accounts after 5 failed login attempts",
                acceptance_criteria=["Account locked after 5 failures", "Lock expires after 15 minutes"],
                effort_estimate="0.5 days",
                risk_level=RiskLevel.MEDIUM,
                dependencies=["TASK-001"],
                related_requirements=["REQ-002"],
            ),
            Task(
                id="TASK-003",
                title="Integrate external payment processor",
                description="Connect to Stripe for payment handling",
                acceptance_criteria=["Successful charge returns order ID", "Failed charge handled gracefully"],
                effort_estimate="3-5 days",
                risk_level=RiskLevel.HIGH,
                dependencies=["TASK-001"],
                related_requirements=["REQ-003"],
            ),
        ]

    return PRDAnalysisResult(
        prd_title="Test PRD",
        requirements=[
            Requirement(
                id="REQ-001",
                type=RequirementType.FUNCTIONAL,
                description="User login",
                priority="high",
            )
        ],
        ambiguities=[
            Ambiguity(
                id="AMB-001",
                location="Payment section",
                issue="Payment methods not specified",
                clarifying_question="Which payment methods should be supported?",
            )
        ],
        tasks=tasks,
        summary=AnalysisSummary(
            total_requirements=1,
            functional_count=1,
            non_functional_count=0,
            ambiguity_count=1,
            total_tasks=len(tasks),
            estimated_total_effort="1-2 weeks",
        ),
    )


# ---------------------------------------------------------------------------
# Tests: to_json / to_dict
# ---------------------------------------------------------------------------

class TestToJson:
    def test_produces_valid_json(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        raw = formatter.to_json(result)
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_round_trips_without_loss(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        restored = PRDAnalysisResult(**formatter.to_dict(result))
        assert restored.prd_title == result.prd_title
        assert len(restored.tasks) == len(result.tasks)

    def test_json_contains_all_sections(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        d = formatter.to_dict(result)
        for key in ("prd_title", "requirements", "ambiguities", "tasks", "summary"):
            assert key in d, f"Missing key: {key}"

    def test_task_has_all_required_fields(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        d = formatter.to_dict(result)
        task = d["tasks"][0]
        for field in ("id", "title", "description", "acceptance_criteria", "effort_estimate", "risk_level"):
            assert field in task, f"Task missing field: {field}"


# ---------------------------------------------------------------------------
# Tests: to_jira_format
# ---------------------------------------------------------------------------

class TestToJiraFormat:
    def test_returns_list_with_correct_length(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        issues = formatter.to_jira_format(result)
        assert len(issues) == len(result.tasks)

    def test_issue_has_required_jira_fields(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        issue = formatter.to_jira_format(result)[0]
        assert "summary" in issue
        assert "description" in issue
        assert "issuetype" in issue
        assert "priority" in issue
        assert "story_points" in issue

    def test_acceptance_criteria_in_description(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        issue = formatter.to_jira_format(result)[0]
        assert "Acceptance Criteria" in issue["description"]
        assert "Returns 200 with token on success" in issue["description"]

    def test_high_risk_maps_to_high_priority(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        issues = formatter.to_jira_format(result)
        high_risk_issue = next(i for i in issues if "Stripe" in i["summary"] or "payment" in i["summary"].lower())
        assert high_risk_issue["priority"]["name"] == "High"

    def test_effort_to_story_points(self) -> None:
        formatter = TaskFormatter()
        assert formatter._effort_to_points("0.5 days") == 1
        assert formatter._effort_to_points("1 day") == 2
        assert formatter._effort_to_points("3-5 days") == 5
        assert formatter._effort_to_points("unknown") == 3


# ---------------------------------------------------------------------------
# Tests: get_high_risk_tasks
# ---------------------------------------------------------------------------

class TestGetHighRiskTasks:
    def test_returns_only_high_risk(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        high_risk = formatter.get_high_risk_tasks(result)
        assert all(t.risk_level == RiskLevel.HIGH for t in high_risk)

    def test_count_matches(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        high_risk = formatter.get_high_risk_tasks(result)
        expected = sum(1 for t in result.tasks if t.risk_level == RiskLevel.HIGH)
        assert len(high_risk) == expected

    def test_empty_when_no_high_risk(self) -> None:
        tasks = [
            Task(
                id="T-001",
                title="Safe task",
                description="Low risk work",
                acceptance_criteria=["Done"],
                effort_estimate="1 day",
                risk_level=RiskLevel.LOW,
            )
        ]
        result = _make_result(tasks=tasks)
        formatter = TaskFormatter()
        assert formatter.get_high_risk_tasks(result) == []


# ---------------------------------------------------------------------------
# Tests: get_dependency_order
# ---------------------------------------------------------------------------

class TestGetDependencyOrder:
    def test_dependencies_come_before_dependents(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        ordered = formatter.get_dependency_order(result)
        ids = [t.id for t in ordered]

        # TASK-002 and TASK-003 both depend on TASK-001
        assert ids.index("TASK-001") < ids.index("TASK-002")
        assert ids.index("TASK-001") < ids.index("TASK-003")

    def test_all_tasks_included(self) -> None:
        result = _make_result()
        formatter = TaskFormatter()
        ordered = formatter.get_dependency_order(result)
        assert len(ordered) == len(result.tasks)

    def test_no_deps_preserved(self) -> None:
        tasks = [
            Task(
                id="T-001",
                title="Task A",
                description="Independent",
                acceptance_criteria=["Done"],
                effort_estimate="1 day",
                risk_level=RiskLevel.LOW,
                dependencies=[],
            ),
            Task(
                id="T-002",
                title="Task B",
                description="Also independent",
                acceptance_criteria=["Done"],
                effort_estimate="1 day",
                risk_level=RiskLevel.LOW,
                dependencies=[],
            ),
        ]
        result = _make_result(tasks=tasks)
        formatter = TaskFormatter()
        ordered = formatter.get_dependency_order(result)
        assert {t.id for t in ordered} == {"T-001", "T-002"}


# ---------------------------------------------------------------------------
# Tests: to_markdown
# ---------------------------------------------------------------------------

class TestToMarkdown:
    def test_contains_title(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "# Test PRD" in md

    def test_contains_summary_table(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "## Summary" in md
        assert "Total Requirements" in md
        assert "Estimated Total Effort" in md

    def test_contains_requirements_section(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "## Requirements" in md
        assert "Functional Requirements" in md
        assert "REQ-001" in md

    def test_contains_ambiguities_section(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "## Ambiguities" in md
        assert "AMB-001" in md
        assert "Payment methods not specified" in md
        assert "Which payment methods" in md

    def test_contains_tasks_section(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "## Development Tasks" in md
        assert "TASK-001" in md
        assert "Implement login endpoint" in md

    def test_tasks_have_acceptance_criteria_checkboxes(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "- [ ] Returns 200 with token" in md
        assert "- [ ] Returns 401 on bad credentials" in md

    def test_tasks_show_effort_and_risk(self) -> None:
        result = _make_result()
        md = TaskFormatter().to_markdown(result)
        assert "1-2 days" in md
        assert "low" in md

    def test_no_ambiguities_section_when_empty(self) -> None:
        result = _make_result(tasks=[
            Task(id="T-1", title="Solo task", description="No ambiguities here",
                 acceptance_criteria=["Done"], effort_estimate="1 day", risk_level=RiskLevel.LOW)
        ])
        # Replace ambiguities with empty list
        import json as json_mod
        from src.models import PRDAnalysisResult
        d = json_mod.loads(result.model_dump_json())
        d["ambiguities"] = []
        d["summary"]["ambiguity_count"] = 0
        result_no_amb = PRDAnalysisResult(**d)
        md = TaskFormatter().to_markdown(result_no_amb)
        assert "## Ambiguities" not in md

    def test_pipe_chars_escaped_in_tables(self) -> None:
        from src.models import Requirement, RequirementType, Priority
        req_with_pipe = Requirement(
            id="REQ-X", type=RequirementType.FUNCTIONAL,
            description="Support A | B formats", priority=Priority.HIGH,
        )
        result = _make_result()
        import json as json_mod
        from src.models import PRDAnalysisResult
        d = json_mod.loads(result.model_dump_json())
        d["requirements"].append(json_mod.loads(req_with_pipe.model_dump_json()))
        d["summary"]["total_requirements"] += 1
        d["summary"]["functional_count"] += 1
        result2 = PRDAnalysisResult(**d)
        md = TaskFormatter().to_markdown(result2)
        # Pipe in description must be escaped so table rows stay valid
        assert "Support A \\| B formats" in md
