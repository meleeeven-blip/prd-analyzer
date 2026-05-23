from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class RequirementType(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    CONSTRAINT = "constraint"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Requirement(BaseModel):
    id: str
    type: RequirementType
    description: str
    priority: Priority
    source_section: Optional[str] = None


class Ambiguity(BaseModel):
    id: str
    location: str
    issue: str
    clarifying_question: str


class Task(BaseModel):
    id: str
    title: str
    description: str
    acceptance_criteria: List[str]
    effort_estimate: str
    risk_level: RiskLevel
    dependencies: List[str] = Field(default_factory=list)
    related_requirements: List[str] = Field(default_factory=list)


class AnalysisSummary(BaseModel):
    total_requirements: int
    functional_count: int
    non_functional_count: int
    ambiguity_count: int
    total_tasks: int
    estimated_total_effort: str


class PRDAnalysisResult(BaseModel):
    prd_title: str
    requirements: List[Requirement]
    ambiguities: List[Ambiguity]
    tasks: List[Task]
    summary: AnalysisSummary
