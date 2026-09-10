"""Request and response models. Pydantic validates every inbound body."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Profile = Literal["learn", "ask", "review"]


class ProjectRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Absolute path to the project folder")


class FileRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Project root")
    file: str = Field(..., min_length=1, description="Project-relative file path")


class ChatRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Project root")
    message: str = Field(..., min_length=1, max_length=8000)
    profile: Profile = "learn"
    session_id: str | None = None


class IndexRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Project root")
    rebuild: bool = False


class SearchRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Project root")
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(6, ge=1, le=20)


class RuntimeInfo(BaseModel):
    api_key_present: bool
    model: str
    base_url: str | None
    provider: str


class HealthResponse(BaseModel):
    app: str
    version: str
    cwd: str
    profiles: list[str]
    runtime: RuntimeInfo
