"""Allow-listed business action contracts.

Definitions describe proposal payloads only. No external executor is registered in this release.
"""
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any


@dataclass(frozen=True)
class ActionField:
    key: str
    kind: str
    required: bool
    description: str
    max_length: int | None = None


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    name: str
    domain: str
    description: str
    risk_level: str
    fields: tuple[ActionField, ...]

    def public_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "risk_level": self.risk_level,
            "fields": [
                {
                    "key": field.key,
                    "kind": field.kind,
                    "required": field.required,
                    "description": field.description,
                    "max_length": field.max_length,
                }
                for field in self.fields
            ],
            "required_approver_roles": ["owner", "admin"],
            "executor_available": False,
            "mode": "proposal_and_approval_only",
        }


_ACTIONS = (
    ActionDefinition(
        id="catalog.product.update",
        name="Update product catalogue data",
        domain="catalog",
        description="Propose a product-field update. No storefront write adapter is installed.",
        risk_level="high",
        fields=(
            ActionField("product_id", "string", True, "Stable product identifier", 160),
            ActionField("changes", "object", True, "Explicit field/value changes"),
            ActionField("expected_version", "string", False, "Optional optimistic-lock version", 120),
        ),
    ),
    ActionDefinition(
        id="inventory.stock.adjust",
        name="Adjust inventory quantity",
        domain="inventory",
        description="Propose a signed stock adjustment for one SKU and location.",
        risk_level="critical",
        fields=(
            ActionField("sku", "string", True, "Stock keeping unit", 120),
            ActionField("location_id", "string", True, "Warehouse or stock location", 160),
            ActionField("quantity_delta", "integer", True, "Signed unit adjustment"),
            ActionField("reason", "string", True, "Reason and supporting evidence", 500),
        ),
    ),
    ActionDefinition(
        id="marketing.campaign.publish",
        name="Publish a marketing campaign",
        domain="marketing",
        description="Propose a campaign publication window and channels.",
        risk_level="high",
        fields=(
            ActionField("campaign_id", "string", True, "Stable campaign identifier", 160),
            ActionField("channels", "string_array", True, "Approved channel identifiers"),
            ActionField("start_at", "string", True, "ISO-8601 start timestamp", 40),
            ActionField("end_at", "string", True, "ISO-8601 end timestamp", 40),
            ActionField("budget_limit", "number", False, "Maximum total budget"),
            ActionField("max_daily_budget", "number", False, "Maximum daily budget"),
        ),
    ),
    ActionDefinition(
        id="orders.refund.issue",
        name="Issue an order refund",
        domain="orders",
        description="Propose a refund amount and reason. No payment adapter is installed.",
        risk_level="critical",
        fields=(
            ActionField("order_id", "string", True, "Stable order identifier", 160),
            ActionField("amount", "number", True, "Refund amount in the stated currency"),
            ActionField("currency", "string", True, "Three-letter ISO currency code", 3),
            ActionField("reason", "string", True, "Refund rationale", 500),
            ActionField("line_item_ids", "string_array", False, "Optional order line items"),
        ),
    ),
)

_ACTION_BY_ID = {action.id: action for action in _ACTIONS}


def list_actions() -> list[ActionDefinition]:
    return list(_ACTIONS)


def get_action(action_id: str) -> ActionDefinition | None:
    return _ACTION_BY_ID.get(action_id)


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_action_inputs(action_id: str, inputs: dict[str, Any]) -> list[str]:
    definition = get_action(action_id)
    if definition is None:
        return ["Unknown action type"]

    fields = {field.key: field for field in definition.fields}
    errors: list[str] = []
    for field in definition.fields:
        if field.required and field.key not in inputs:
            errors.append(f"{field.key}: field is required")

    for key, value in inputs.items():
        field = fields.get(key)
        if field is None:
            errors.append(f"{key}: field is not allowed for this action")
            continue
        if field.kind == "string":
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{key}: expected a non-empty string")
            elif field.max_length is not None and len(value) > field.max_length:
                errors.append(f"{key}: must be at most {field.max_length} characters")
        elif field.kind == "object":
            if not isinstance(value, dict) or not value:
                errors.append(f"{key}: expected a non-empty object")
        elif field.kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{key}: expected an integer")
        elif field.kind == "number":
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                errors.append(f"{key}: expected a finite positive number")
        elif field.kind == "string_array":
            if (
                not isinstance(value, list)
                or not value
                or len(value) > 50
                or not all(isinstance(item, str) and item.strip() for item in value)
            ):
                errors.append(f"{key}: expected a non-empty array of at most 50 strings")

    if action_id == "orders.refund.issue" and isinstance(inputs.get("currency"), str):
        currency = inputs["currency"]
        if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
            errors.append("currency: expected a three-letter uppercase currency code")

    if action_id == "marketing.campaign.publish":
        start = inputs.get("start_at")
        end = inputs.get("end_at")
        if isinstance(start, str) and _parse_iso_datetime(start) is None:
            errors.append("start_at: expected an ISO-8601 timestamp with timezone")
        if isinstance(end, str) and _parse_iso_datetime(end) is None:
            errors.append("end_at: expected an ISO-8601 timestamp with timezone")
        if isinstance(start, str) and isinstance(end, str):
            parsed_start = _parse_iso_datetime(start)
            parsed_end = _parse_iso_datetime(end)
            if parsed_start is not None and parsed_end is not None and parsed_end <= parsed_start:
                errors.append("end_at: must be later than start_at")

    return errors


def executor_available(action_id: str) -> bool:
    """Fail closed: this release intentionally has no external action adapters."""
    return False
