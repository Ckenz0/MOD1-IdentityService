"""Own-account profile contract; no directory or caller-selected user IDs."""

import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Seniority = Literal["not_informed", "junior", "mid", "senior", "lead"]


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=1, le=5)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


Skills = Annotated[list[Skill], Field(max_length=30)]


class Profile(BaseModel):
    user_id: UUID
    summary: str = ""
    seniority: Seniority = "not_informed"
    weekly_availability_hours: int = 0
    skills: list[Skill] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Defaults allow omission only; explicit null still fails the non-null field type.
    summary: str = Field(default="", max_length=2000)
    seniority: Seniority = "not_informed"
    weekly_availability_hours: int = Field(default=0, ge=0, le=168)
    skills: Skills = Field(default_factory=list)

    @field_validator("skills")
    @classmethod
    def unique_skills(cls, values: list[Skill]) -> list[Skill]:
        keys = [unicodedata.normalize("NFC", skill.name).casefold() for skill in values]
        if len(set(keys)) != len(keys):
            raise ValueError("Skill names must be unique")
        return values

    @model_validator(mode="after")
    def nonempty_patch(self) -> "ProfilePatch":
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        return self
