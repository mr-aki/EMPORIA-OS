from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


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
    web_research: bool = False
    research_query: str | None = Field(default=None, min_length=1, max_length=600)

    @model_validator(mode="after")
    def require_explicit_research_query(self):
        if self.web_research and not self.research_query:
            raise ValueError(
                "research_query is required when web_research is enabled; "
                "the task text is never sent to external search automatically"
            )
        if self.web_research and len(self.task) > 7000:
            raise ValueError(
                "task must be at most 7000 characters when web research is enabled"
            )
        return self


class ResearchSourceRead(BaseModel):
    index: int
    url: str
    title: str
    hostname: str
    snippets: list[str]
    age: list[str]


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
    research_sources: list[ResearchSourceRead] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ResearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    maximum_number_of_tokens: int = Field(default=4000, ge=1024, le=8192)



class ResearchRead(BaseModel):
    query: str
    sources: list[ResearchSourceRead]
    request_id: str | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    workspace_name: str = Field(min_length=1, max_length=160)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=36)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class AuthTokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    workspace_id: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    role: str


class WorkspaceCreated(WorkspaceSummary):
    created_at: datetime


class AuthMeRead(BaseModel):
    user_id: str
    email: EmailStr
    display_name: str
    is_active: bool
    workspaces: list[WorkspaceSummary]
