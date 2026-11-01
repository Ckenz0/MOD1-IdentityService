"""Provider-neutral, strict anomaly recommendation contract."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnomalySuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    action: Literal["review_access", "review_login", "review_sessions"]
    reason: str = Field(min_length=1, max_length=500)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=50)


class AnomalyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(min_length=1, max_length=50)
    suggestions: list[AnomalySuggestion] = Field(min_length=1, max_length=50)
