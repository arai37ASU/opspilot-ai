"""Request and response models. FastAPI uses them to validate input and
output and to document the API at /docs."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str = Field(description='"ok" when the database answers and the model is loaded')
    database: str
    model_loaded: bool


class HeldOutMetrics(BaseModel):
    average_precision: float
    roc_auc: float
    brier: float
    expected_calibration_error: float
    share_flagged: float
    precision_at_threshold: float
    recall_at_threshold: float


class ModelInfo(BaseModel):
    model: str = Field(description="Model family selected on the validation folds")
    threshold: float = Field(description="Tickets with predicted risk at or above this are flagged")
    features: list[str]
    train_period: list[str]
    commit: str = Field(description="Git commit the model was trained and evaluated from")
    test_period: list[str]
    test_metrics: HeldOutMetrics = Field(description="From the single evaluation on the held-out test period")


class TicketRequest(BaseModel):
    """What is known about a ticket when it is submitted."""
    created_at: datetime = Field(description="Submission time, campus local time, inside the period covered by the data",
                                 examples=["2025-09-03T19:30:00"])
    priority: Literal["P1", "P2", "P3", "P4"]
    subcategory: str = Field(examples=["projector_display"])
    assigned_team: str = Field(examples=["Classroom Technology"])
    requester_type: Literal["student", "faculty", "staff"]
    channel: Literal["portal", "email", "phone", "chat", "walk_in"]


class Reason(BaseModel):
    feature: str
    value: str | float | int | bool | None
    contribution: float = Field(description="SHAP value in log-odds: positive raises the risk, negative lowers it")
    direction: Literal["raises risk", "lowers risk"]


class Prediction(BaseModel):
    risk: float = Field(ge=0, le=1, description="Predicted probability that the ticket breaches its SLA")
    flagged: bool = Field(description="Whether the risk is at or above the operating threshold")
    threshold: float
    reasons: list[Reason] = Field(description="The features that moved this ticket's risk the most")
    inputs: dict[str, str | float | None] = Field(description="The exact feature values the model received")
    model: str


class PriorityRate(BaseModel):
    priority: str
    resolved: int
    breach_rate_pct: float | None


class Overview(BaseModel):
    start: date
    end: date
    tickets: int
    resolved: int
    unresolved: int = Field(description="Open or in progress at the data snapshot")
    breached: int
    breach_rate_pct: float | None = Field(description="Share of resolved tickets that missed their SLA")
    median_resolution_hours: float | None
    mean_satisfaction: float | None = Field(description="Survey respondents only; responses lean toward extreme experiences")
    survey_response_rate_pct: float | None
    by_priority: list[PriorityRate]


class TeamMetrics(BaseModel):
    team: str
    agents: int = Field(description="Current headcount from the teams table. Past staffing changes, such as "
                                    "Desktop Support's reduction in April-June 2025, are not recorded.")
    tickets: int = Field(description="Tickets first assigned to the team")
    resolved: int = Field(description="Tickets the team resolved")
    breach_rate_pct: float | None
    median_resolution_hours: float | None
    misrouted_pct: float | None = Field(description="Share of tickets assigned to the team that belonged to another team")


class Teams(BaseModel):
    start: date
    end: date
    teams: list[TeamMetrics]


class MonthPoint(BaseModel):
    month: date
    tickets: int
    breach_rate_pct: float | None


class AnalysisQuery(BaseModel):
    file: str
    query: str
    description: str
    path: str


class AnalysisResult(BaseModel):
    file: str
    query: str
    rows: list[dict[str, Any]]


class TicketRisk(Prediction):
    ticket_id: str
    created_at: datetime
    status: str
    sla_breached: bool | None = Field(description="Known outcome, if resolved. Not used by the model; shown for comparison.")
