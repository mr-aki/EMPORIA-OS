import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from emporia_api.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)




class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class Venture(Base):
    __tablename__ = "ventures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planning", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_agent_runs_workspace_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requested_max_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    budget_charged_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    research_sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def research_sources(self) -> list[dict[str, object]]:
        try:
            value = json.loads(self.research_sources_json or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    @research_sources.setter
    def research_sources(self, value: list[dict[str, object]]) -> None:
        self.research_sources_json = json.dumps(value, ensure_ascii=False)



class WorkspaceExecutionRateLimit(Base):
    __tablename__ = "workspace_execution_rate_limits"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "execution_type",
            name="uq_workspace_execution_rate_limit",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    execution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkspaceOutputTokenBudget(Base):
    __tablename__ = "workspace_output_token_budgets"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_output_token_budget"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    monthly_output_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SkillRun(Base):
    __tablename__ = "skill_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_skill_runs_workspace_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    inputs_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evaluation_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requested_max_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    budget_charged_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def evaluation(self) -> dict[str, Any] | None:
        if self.status != "completed":
            return None
        try:
            value = json.loads(self.evaluation_json or "{}")
        except (TypeError, ValueError):
            value = {}
        if isinstance(value, dict) and value:
            return value

        # Backfill-compatible fallback for completed runs created before snapshots existed.
        from emporia_api.skills.evaluation import evaluate_skill_output
        from emporia_api.skills.registry import get_skill

        skill = get_skill(self.skill_id)
        if skill is None or skill.version != self.skill_version:
            return None
        return evaluate_skill_output(skill, self.output)
    @property
    def inputs(self) -> dict[str, Any]:
        try:
            value = json.loads(self.inputs_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @property
    def calculations(self) -> dict[str, Any]:
        from emporia_api.skills.calculations import calculate_skill
        from emporia_api.skills.registry import get_skill

        skill = get_skill(self.skill_id)
        if skill is None or skill.version != self.skill_version:
            return {}
        return calculate_skill(self.skill_id, self.inputs)



class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_background_jobs_workspace_idempotency_key",
        ),
        Index("ix_background_jobs_status_available_at", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}



class BusinessActionRequest(Base):
    __tablename__ = "business_action_requests"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_business_action_idempotency",
        ),
        Index("ix_business_action_requests_status_requested_at", "status", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="pending_approval", server_default="pending_approval", nullable=False
    )
    requested_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rejected_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_block_reason: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def inputs(self) -> dict[str, Any]:
        try:
            value = json.loads(self.inputs_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
