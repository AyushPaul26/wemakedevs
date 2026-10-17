"""Validated public request contracts for the single-workspace application."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationRequest(Request):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")] | None = None


class RippleRequest(Request):
    origin_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    mitigation: bool = False


class SourceRequest(Request):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30000)]
    type: Literal["document"] = "document"
