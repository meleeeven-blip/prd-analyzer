from __future__ import annotations

import json
import os
from typing import Optional

from openai import OpenAI

from .models import (
    AnalysisSummary,
    Ambiguity,
    PRDAnalysisResult,
    Requirement,
    RequirementType,
    Task,
)

# Alibaba Bailian (DashScope) OpenAI-compatible endpoint
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# Default to deepseek-v4-flash (available on Bailian free tier).
# Switch to "qwen-plus" or "qwen-max" for higher quality with a paid account.
DEFAULT_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = """You are an expert software engineering consultant specializing in analyzing \
product requirements documents (PRDs) and creating structured development task breakdowns.

Your responsibilities:
1. Extract every functional requirement, non-functional requirement, and constraint from the PRD
2. Identify ambiguities, missing information, and unclear specifications
3. Generate clear, actionable development tasks with testable acceptance criteria
4. Estimate realistic effort and identify technical risks

Be thorough. A missed requirement discovered mid-sprint costs 10x more than catching it now."""

# OpenAI tool format: wrap schema under {"type": "function", "function": {..., "parameters": ...}}
EXTRACT_REQUIREMENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_requirements",
        "description": "Extract structured requirements and ambiguities from a PRD",
        "parameters": {
            "type": "object",
            "properties": {
                "requirements": {
                    "type": "array",
                    "description": "All requirements extracted from the PRD",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique ID like REQ-001"},
                            "type": {
                                "type": "string",
                                "enum": ["functional", "non_functional", "constraint"],
                            },
                            "description": {"type": "string"},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            "source_section": {
                                "type": "string",
                                "description": "Which section of the PRD this came from",
                            },
                        },
                        "required": ["id", "type", "description", "priority"],
                    },
                },
                "ambiguities": {
                    "type": "array",
                    "description": "Unclear or missing information that needs PM clarification",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique ID like AMB-001"},
                            "location": {
                                "type": "string",
                                "description": "Which section or requirement this refers to",
                            },
                            "issue": {"type": "string", "description": "What is unclear or missing"},
                            "clarifying_question": {
                                "type": "string",
                                "description": "Specific question to ask the PM",
                            },
                        },
                        "required": ["id", "location", "issue", "clarifying_question"],
                    },
                },
            },
            "required": ["requirements", "ambiguities"],
        },
    },
}

GENERATE_TASKS_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_tasks",
        "description": "Generate development tasks from extracted requirements",
        "parameters": {
            "type": "object",
            "properties": {
                "prd_title": {"type": "string", "description": "Title of the PRD"},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique ID like TASK-001"},
                            "title": {"type": "string", "description": "Short, action-oriented title"},
                            "description": {
                                "type": "string",
                                "description": "What needs to be built and why",
                            },
                            "acceptance_criteria": {
                                "type": "array",
                                "description": "Specific, testable conditions for done (2 items max)",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "effort_estimate": {
                                "type": "string",
                                "description": "e.g. '0.5 days', '1-2 days', '3-5 days'",
                            },
                            "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
                            "dependencies": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "IDs of tasks that must complete first",
                            },
                            "related_requirements": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Requirement IDs this task fulfills",
                            },
                        },
                        "required": [
                            "id",
                            "title",
                            "description",
                            "acceptance_criteria",
                            "effort_estimate",
                            "risk_level",
                        ],
                    },
                },
                "estimated_total_effort": {
                    "type": "string",
                    "description": "Total estimated effort, e.g. '2-3 weeks'",
                },
            },
            "required": ["prd_title", "tasks", "estimated_total_effort"],
        },
    },
}


class PRDAnalyzer:
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.client = OpenAI(
            api_key=api_key or os.environ.get("DASHSCOPE_API_KEY"),
            base_url=BAILIAN_BASE_URL,
        )
        self.model = model

    def analyze(self, prd_text: str) -> PRDAnalysisResult:
        requirements_data, ambiguities_data = self._extract_requirements(prd_text)
        tasks_data, prd_title, estimated_effort = self._generate_tasks(
            prd_text, requirements_data, ambiguities_data
        )

        requirements = [Requirement(**self._normalize_requirement(r)) for r in requirements_data]
        ambiguities = [Ambiguity(**self._normalize_ambiguity(a)) for a in ambiguities_data]
        tasks = [Task(**self._normalize_task(t)) for t in tasks_data]

        functional_count = sum(
            1 for r in requirements if r.type == RequirementType.FUNCTIONAL
        )
        non_functional_count = sum(
            1 for r in requirements if r.type == RequirementType.NON_FUNCTIONAL
        )

        summary = AnalysisSummary(
            total_requirements=len(requirements),
            functional_count=functional_count,
            non_functional_count=non_functional_count,
            ambiguity_count=len(ambiguities),
            total_tasks=len(tasks),
            estimated_total_effort=estimated_effort,
        )

        return PRDAnalysisResult(
            prd_title=prd_title,
            requirements=requirements,
            ambiguities=ambiguities,
            tasks=tasks,
            summary=summary,
        )

    def _extract_requirements(self, prd_text: str) -> tuple[list, list]:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=8192,
            tools=[EXTRACT_REQUIREMENTS_TOOL],
            tool_choice="required",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请分析以下产品需求文档（PRD）。\n\n"
                        "<prd>\n"
                        f"{prd_text}\n"
                        "</prd>\n\n"
                        "请调用 extract_requirements 函数，返回：\n"
                        "1. 文档中所有功能需求、非功能需求和约束条件\n"
                        "2. 所有歧义、描述不清或缺失的信息\n\n"
                        "重要：description、issue、clarifying_question 等所有文本字段必须使用中文填写。\n"
                        "请务必全面——即使是隐含的需求也要捕捉到。"
                    ),
                },
            ],
        )

        args = self._get_tool_args(response, "extract_requirements")
        return args["requirements"], args["ambiguities"]

    def _generate_tasks(
        self, prd_text: str, requirements: list, ambiguities: list
    ) -> tuple[list, str, str]:
        req_json = json.dumps(requirements, ensure_ascii=False, indent=2)
        amb_json = json.dumps(ambiguities, ensure_ascii=False, indent=2)

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=16000,
            tools=[GENERATE_TASKS_TOOL],
            tool_choice="required",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请根据以下 PRD 和已提取的需求，生成研发任务拆解。\n\n"
                        "<prd>\n"
                        f"{prd_text}\n"
                        "</prd>\n\n"
                        "<extracted_requirements>\n"
                        f"{req_json}\n"
                        "</extracted_requirements>\n\n"
                        "<identified_ambiguities>\n"
                        f"{amb_json}\n"
                        "</identified_ambiguities>\n\n"
                        "请调用 generate_tasks 函数，生成任务，严格要求：\n"
                        "- 标题不超过15个字，以动作开头（如「实现用户登录接口」）\n"
                        "- 每个任务恰好 2 条验收标准，每条不超过20个字\n"
                        "- description 不超过30个字，说明做什么即可\n"
                        "- 合理的工时估算（单任务不超过 5 天，超出则拆分）\n"
                        "- 有依赖关系的任务标注依赖\n"
                        "- 根据技术复杂度和不确定性评定风险等级\n"
                        "重要：所有文本字段必须使用中文填写。输出必须简洁，避免截断。"
                    ),
                },
            ],
        )

        args = self._get_tool_args(response, "generate_tasks")
        return args["tasks"], args["prd_title"], args["estimated_total_effort"]

    def _get_tool_args(self, response, expected_tool: str) -> dict:
        """Extract and JSON-parse the first tool call matching expected_tool."""
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError(
                f"Response truncated: model hit max_tokens limit while generating "
                f"{expected_tool}. Try a shorter PRD or increase max_tokens."
            )
        message = choice.message
        tool_calls = message.tool_calls or []
        for tc in tool_calls:
            if tc.function.name == expected_tool:
                try:
                    return json.loads(tc.function.arguments)
                except json.JSONDecodeError as e:
                    snippet = tc.function.arguments[max(0, e.pos - 40): e.pos + 40]
                    raise ValueError(
                        f"JSON parse error in {expected_tool} at char {e.pos}: {e.msg}. "
                        f"Context: ...{snippet!r}..."
                    ) from e
        raise ValueError(f"Model did not invoke {expected_tool} function")

    # Priority / risk aliases that some models emit instead of high/medium/low
    _PRIORITY_MAP = {
        "critical": "high", "urgent": "high", "highest": "high",
        "low-medium": "medium", "medium-high": "medium", "normal": "medium",
        "minor": "low", "lowest": "low", "nice-to-have": "low",
    }

    @classmethod
    def _normalize_requirement(cls, r: dict) -> dict:
        r = dict(r)
        r["priority"] = cls._PRIORITY_MAP.get(str(r.get("priority", "")).lower(), r.get("priority", "medium"))
        req_type = str(r.get("type", "")).lower()
        if req_type in ("non-functional", "nonfunctional", "non functional"):
            r["type"] = "non_functional"
        return r

    @classmethod
    def _normalize_task(cls, t: dict) -> dict:
        t = dict(t)
        t["risk_level"] = cls._PRIORITY_MAP.get(str(t.get("risk_level", "")).lower(), t.get("risk_level", "medium"))
        return t

    @staticmethod
    def _normalize_ambiguity(a: dict) -> dict:
        """Normalize alternative field names that models sometimes emit."""
        if "clarifying_question" not in a:
            for alt in ("question", "clarification_question", "clarification", "suggested_question"):
                if alt in a:
                    a["clarifying_question"] = a.pop(alt)
                    break
            else:
                a["clarifying_question"] = a.get("issue", "Please clarify this requirement.")
        return a
