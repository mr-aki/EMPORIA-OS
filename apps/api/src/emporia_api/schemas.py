from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class VentureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)


class VentureUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["planning", "active", "paused", "archived"] | None = None


class VentureRead(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditRead(BaseModel):
    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    detail: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


ModelName = Annotated[str, StringConstraints(
    min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
)]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class ChatCompletionRequest(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "openai-compatible"]
    model: ModelName
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def require_user_message(self):
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("At least one user message is required")
        return self


class ChatUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionRead(BaseModel):
    provider: str
    model: str
    content: str
    usage: ChatUsage
    provider_request_id: str | None = None


class ProviderRead(BaseModel):
    id: str
    name: str
    configured: bool
    protocol: str
    docs_url: str


class AgentRead(BaseModel):
    id: str
    name: str
    version: str
    mission: str
    expertise: list[str]
    tools_enabled: bool = False


class AgentRunCreate(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "openai-compatible"]
    model: ModelName
    task: str = Field(min_length=1, max_length=12000)
    max_tokens: int = Field(default=1800, ge=1, le=4096)
    temperature: float | None = Field(default=0.2, ge=0, le=2)


class AgentRunRead(BaseModel):
    id: str
    agent_id: str
    agent_version: str
    provider: str
    model: str
    status: Literal["running", "completed", "failed"]
    task: str
    output: str
    error_message: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    provider_request_id: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
