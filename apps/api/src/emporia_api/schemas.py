import json
from datetime import date as Date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
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
    category: str
    deliverables: list[str]
    required_context: list[str]
    tools_enabled: bool = False


class AgentRunCreate(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "openai-compatible"]
    model: ModelName
    task: str = Field(min_length=1, max_length=12000)
    max_tokens: int = Field(default=1800, ge=1, le=4096)
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    web_research: bool = False
    research_query: str | None = Field(default=None, min_length=1, max_length=600)
    research_country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    research_lang: str = Field(
        default="en",
        min_length=2,
        max_length=8,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?$",
    )

    @field_validator("research_country", mode="before")
    @classmethod
    def normalize_research_country(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("research_lang", mode="before")
    @classmethod
    def normalize_research_language(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("research_query", mode="before")
    @classmethod
    def normalize_research_query(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("research_query must not be blank")
        return normalized

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
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    search_lang: str = Field(
        default="en",
        min_length=2,
        max_length=8,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?$",
    )
    maximum_number_of_tokens: int = Field(default=4000, ge=1024, le=32768)

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("search_lang", mode="before")
    @classmethod
    def normalize_search_language(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized



class ResearchRead(BaseModel):
    query: str
    sources: list[ResearchSourceRead]
    request_id: str | None = None


class SkillInputRead(BaseModel):
    key: str
    label: str
    value_type: Literal["text", "number", "object", "array"]
    required: bool
    description: str
    max_length: int | None = None
    max_items: int | None = None
    minimum: float | None = None
    maximum: float | None = None


class SkillRead(BaseModel):
    id: str
    name: str
    version: str
    domain: str
    description: str
    objective: str
    inputs: list[SkillInputRead]
    output_sections: list[str]
    lifecycle_status: str
    execution_mode: Literal["advisory"] = "advisory"
    external_actions_enabled: bool = False


class SkillRunCreate(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "openai-compatible"]
    model: ModelName
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int = Field(default=1800, ge=1, le=4096)
    temperature: float | None = Field(default=0.2, ge=0, le=2)

    @model_validator(mode="after")
    def bound_input_payload(self):
        if len(self.inputs) > 32:
            raise ValueError("At most 32 skill input fields are allowed")
        try:
            serialized = json.dumps(self.inputs, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("inputs must contain JSON-safe values") from exc
        if len(serialized.encode("utf-8")) > 16000:
            raise ValueError("Serialized skill inputs must be at most 16000 bytes")
        return self


class SkillRunRead(BaseModel):
    id: str
    skill_id: str
    skill_version: str
    provider: str
    model: str
    status: Literal["running", "completed", "failed"]
    inputs: dict[str, Any]
    output: str
    error_message: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    provider_request_id: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$")]


class FXRateRead(BaseModel):
    base: str
    quote: str
    rate: Decimal
    date: Date
    provider: Literal["frankfurter"] = "frankfurter"
    rate_basis: Literal["daily_reference_mid_market"] = "daily_reference_mid_market"
    provider_url: str = "https://frankfurter.dev/"


class FXConvertRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=28, decimal_places=12)
    base: CurrencyCode
    quote: CurrencyCode
    date: Date | None = None

    @field_validator("base", "quote", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_conversion(self):
        if self.base == self.quote:
            raise ValueError("Base and quote currencies must be different")
        if self.date is not None and self.date > Date.today():
            raise ValueError("Future exchange-rate dates are not supported")
        return self


class FXConvertRead(BaseModel):
    amount: Decimal
    converted_amount: Decimal
    base: str
    quote: str
    rate: Decimal
    date: Date
    provider: Literal["frankfurter"] = "frankfurter"
    rate_basis: Literal["daily_reference_mid_market"] = "daily_reference_mid_market"
    provider_url: str = "https://frankfurter.dev/"
    disclaimer: str = (
        "Daily reference rate, not a live trading quote or guaranteed settlement rate."
    )
