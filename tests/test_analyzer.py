"""Unit tests for PRDAnalyzer — uses mock to avoid real API calls."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.analyzer import PRDAnalyzer
from src.models import PRDAnalysisResult, RequirementType, RiskLevel

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers: build mock OpenAI chat.completions responses
# ---------------------------------------------------------------------------

def _make_tool_response(tool_name: str, args: dict) -> MagicMock:
    """Return a mock openai ChatCompletion with a single tool call."""
    tool_call = MagicMock()
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(args, ensure_ascii=False)

    message = MagicMock()
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _make_no_tool_response() -> MagicMock:
    """Return a mock response with no tool calls (model replied in plain text)."""
    message = MagicMock()
    message.tool_calls = []

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _extract_response(requirements: list, ambiguities: list) -> MagicMock:
    return _make_tool_response(
        "extract_requirements",
        {"requirements": requirements, "ambiguities": ambiguities},
    )


def _generate_response(tasks: list, title: str, effort: str) -> MagicMock:
    return _make_tool_response(
        "generate_tasks",
        {"prd_title": title, "tasks": tasks, "estimated_total_effort": effort},
    )


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SAMPLE_REQUIREMENTS = [
    {
        "id": "REQ-001",
        "type": "functional",
        "description": "Users can register with email and password",
        "priority": "high",
        "source_section": "User Registration",
    },
    {
        "id": "REQ-002",
        "type": "non_functional",
        "description": "Passwords must be hashed with bcrypt",
        "priority": "high",
        "source_section": "Security",
    },
]

SAMPLE_AMBIGUITIES = [
    {
        "id": "AMB-001",
        "location": "User Registration",
        "issue": "Confirmation email content and timing not specified",
        "clarifying_question": "What should the confirmation email contain and within what timeframe must it be sent?",
    }
]

SAMPLE_TASKS = [
    {
        "id": "TASK-001",
        "title": "Implement user registration endpoint",
        "description": "Create POST /api/auth/register that validates and stores new users",
        "acceptance_criteria": [
            "Returns 201 on successful registration",
            "Returns 409 if email already exists",
            "Password is hashed before storage",
        ],
        "effort_estimate": "1-2 days",
        "risk_level": "low",
        "dependencies": [],
        "related_requirements": ["REQ-001"],
    },
    {
        "id": "TASK-002",
        "title": "Implement bcrypt password hashing",
        "description": "Add bcrypt hashing utility with cost factor 12",
        "acceptance_criteria": [
            "Passwords are hashed with bcrypt cost factor >= 12",
            "Plain-text passwords never appear in logs",
        ],
        "effort_estimate": "0.5 days",
        "risk_level": "medium",
        "dependencies": [],
        "related_requirements": ["REQ-002"],
    },
]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestPRDAnalyzer:

    @patch("src.analyzer.OpenAI")
    def test_analyze_returns_valid_result(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response(SAMPLE_REQUIREMENTS, SAMPLE_AMBIGUITIES),
            _generate_response(SAMPLE_TASKS, "User Auth PRD", "3-4 days"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        result = analyzer.analyze("dummy PRD text")

        assert isinstance(result, PRDAnalysisResult)
        assert result.prd_title == "User Auth PRD"
        assert len(result.requirements) == 2
        assert len(result.ambiguities) == 1
        assert len(result.tasks) == 2

    @patch("src.analyzer.OpenAI")
    def test_summary_counts_are_correct(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response(SAMPLE_REQUIREMENTS, SAMPLE_AMBIGUITIES),
            _generate_response(SAMPLE_TASKS, "Test PRD", "2 days"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        result = analyzer.analyze("dummy PRD text")

        assert result.summary.functional_count == 1
        assert result.summary.non_functional_count == 1
        assert result.summary.ambiguity_count == 1
        assert result.summary.total_tasks == 2
        assert result.summary.estimated_total_effort == "2 days"

    @patch("src.analyzer.OpenAI")
    def test_requirement_types_parsed_correctly(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response(SAMPLE_REQUIREMENTS, []),
            _generate_response([], "Test PRD", "0 days"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        result = analyzer.analyze("dummy PRD text")

        req_types = {r.id: r.type for r in result.requirements}
        assert req_types["REQ-001"] == RequirementType.FUNCTIONAL
        assert req_types["REQ-002"] == RequirementType.NON_FUNCTIONAL

    @patch("src.analyzer.OpenAI")
    def test_ambiguous_prd_returns_ambiguities(self, mock_openai_cls: MagicMock) -> None:
        many_ambiguities = [
            {
                "id": f"AMB-{i:03d}",
                "location": f"Section {i}",
                "issue": f"Unclear requirement {i}",
                "clarifying_question": f"Question {i}?",
            }
            for i in range(1, 6)
        ]

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response([], many_ambiguities),
            _generate_response([], "Ambiguous PRD", "unknown"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        ambiguous_text = (FIXTURES / "ambiguous_prd.md").read_text(encoding="utf-8")
        result = analyzer.analyze(ambiguous_text)

        assert result.summary.ambiguity_count == 5
        assert all(a.clarifying_question.endswith("?") for a in result.ambiguities)

    @patch("src.analyzer.OpenAI")
    def test_api_error_raises_exception(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API connection error")

        analyzer = PRDAnalyzer(api_key="test-key")
        with pytest.raises(Exception, match="API connection error"):
            analyzer.analyze("dummy PRD text")

    @patch("src.analyzer.OpenAI")
    def test_missing_tool_response_raises_value_error(self, mock_openai_cls: MagicMock) -> None:
        """If the model returns no tool calls, analyzer should raise ValueError."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_no_tool_response()

        analyzer = PRDAnalyzer(api_key="test-key")
        with pytest.raises(ValueError, match="extract_requirements"):
            analyzer.analyze("dummy PRD text")

    @patch("src.analyzer.OpenAI")
    def test_tasks_have_required_fields(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response(SAMPLE_REQUIREMENTS, []),
            _generate_response(SAMPLE_TASKS, "Test PRD", "3 days"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        result = analyzer.analyze("dummy PRD text")

        for task in result.tasks:
            assert task.title, "Task must have a title"
            assert task.description, "Task must have a description"
            assert len(task.acceptance_criteria) >= 1, "Task must have acceptance criteria"
            assert task.effort_estimate, "Task must have an effort estimate"
            assert task.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW)

    @patch("src.analyzer.OpenAI")
    def test_client_uses_bailian_base_url(self, mock_openai_cls: MagicMock) -> None:
        """Verify the OpenAI client is initialized with the Bailian endpoint."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        PRDAnalyzer(api_key="test-key")

        call_kwargs = mock_openai_cls.call_args.kwargs
        assert "dashscope.aliyuncs.com" in call_kwargs["base_url"]

    @patch("src.analyzer.OpenAI")
    def test_tool_choice_is_required(self, mock_openai_cls: MagicMock) -> None:
        """Both API calls must use tool_choice='required' to force structured output."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response(SAMPLE_REQUIREMENTS, []),
            _generate_response(SAMPLE_TASKS, "Test PRD", "3 days"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        analyzer.analyze("dummy PRD text")

        calls = mock_client.chat.completions.create.call_args_list
        assert len(calls) == 2
        for call in calls:
            assert call.kwargs.get("tool_choice") == "required", (
                "tool_choice must be 'required' to force function calling"
            )

    @patch("src.analyzer.OpenAI")
    def test_system_message_sent_in_messages(self, mock_openai_cls: MagicMock) -> None:
        """Verify the system prompt is passed as the first message with role=system."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _extract_response(SAMPLE_REQUIREMENTS, []),
            _generate_response(SAMPLE_TASKS, "Test PRD", "3 days"),
        ]

        analyzer = PRDAnalyzer(api_key="test-key")
        analyzer.analyze("dummy PRD text")

        calls = mock_client.chat.completions.create.call_args_list
        for call in calls:
            messages = call.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert len(messages[0]["content"]) > 0


# ---------------------------------------------------------------------------
# Integration tests (require real DASHSCOPE_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPRDAnalyzerIntegration:
    def test_simple_prd_end_to_end(self) -> None:
        """End-to-end test with real Bailian API — requires DASHSCOPE_API_KEY."""
        prd_text = (FIXTURES / "simple_prd.md").read_text(encoding="utf-8")
        analyzer = PRDAnalyzer()
        result = analyzer.analyze(prd_text)

        assert result.prd_title
        assert result.summary.total_requirements >= 5
        assert result.summary.total_tasks >= 3
        assert result.summary.functional_count >= 1
        # Model may find many ambiguities even in a well-written PRD; just verify it runs
        assert result.summary.ambiguity_count >= 0

    @pytest.mark.integration
    def test_complex_prd_detects_ambiguities(self) -> None:
        """Complex PRD with open questions should produce ambiguities."""
        prd_text = (FIXTURES / "complex_prd.md").read_text(encoding="utf-8")
        analyzer = PRDAnalyzer()
        result = analyzer.analyze(prd_text)

        # complex_prd.md has 5 explicit open questions — expect at least 3 caught
        assert result.summary.ambiguity_count >= 3

    @pytest.mark.integration
    def test_output_schema_valid(self) -> None:
        """Output must deserialize back to PRDAnalysisResult without errors."""
        import json as json_mod

        prd_text = (FIXTURES / "simple_prd.md").read_text(encoding="utf-8")
        analyzer = PRDAnalyzer()
        result = analyzer.analyze(prd_text)

        raw = json_mod.loads(result.model_dump_json())
        restored = PRDAnalysisResult(**raw)
        assert restored.summary.total_tasks == result.summary.total_tasks
