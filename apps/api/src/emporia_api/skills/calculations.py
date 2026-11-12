"""Deterministic calculations for commerce skills.

These functions use Decimal arithmetic and are authoritative for the numeric outputs
shown to model providers. They intentionally calculate only from operator-supplied
inputs and surface assumptions instead of inferring missing business data.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

FOUR_PLACES = Decimal("0.0001")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _rounded(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP))


def _landed_cost(inputs: dict[str, Any]) -> dict[str, Any]:
    units = _d(inputs["units_per_shipment"])
    unit_cost = _d(inputs["supplier_unit_cost"])
    freight_total = _d(inputs["freight_total"])
    duty_rate = _d(inputs["duty_rate_percent"]) / Decimal(100)
    other_costs = _d(inputs["other_costs_per_unit"])
    selling_price = _d(inputs["selling_price"])
    channel_fee_rate = _d(inputs.get("channel_fee_percent", 0)) / Decimal(100)

    explicit_duty_base = inputs.get("duty_base_per_unit")
    duty_base = _d(explicit_duty_base) if explicit_duty_base is not None else unit_cost
    freight_per_unit = freight_total / units
    duty_per_unit = duty_base * duty_rate
    landed_cost = unit_cost + freight_per_unit + duty_per_unit + other_costs
    channel_fee = selling_price * channel_fee_rate
    contribution = selling_price - channel_fee - landed_cost
    margin = (
        contribution / selling_price * Decimal(100)
        if selling_price > 0 else None
    )
    break_even = (
        landed_cost / (Decimal(1) - channel_fee_rate)
        if channel_fee_rate < 1 else None
    )

    return {
        "calculation_type": "landed-cost-margin",
        "currency": str(inputs["currency"]).upper(),
        "units_per_shipment": int(units),
        "freight_per_unit": _rounded(freight_per_unit),
        "duty_base_per_unit": _rounded(duty_base),
        "duty_base_source": (
            "operator_supplied" if explicit_duty_base is not None
            else "provisional_supplier_unit_cost"
        ),
        "duty_per_unit": _rounded(duty_per_unit),
        "other_costs_per_unit": _rounded(other_costs),
        "landed_cost_per_unit": _rounded(landed_cost),
        "selling_price": _rounded(selling_price),
        "channel_fee_per_unit": _rounded(channel_fee),
        "contribution_per_unit": _rounded(contribution),
        "contribution_margin_percent": _rounded(margin),
        "break_even_selling_price": _rounded(break_even),
        "formulas": {
            "freight_per_unit": "freight_total / units_per_shipment",
            "duty_per_unit": "duty_base_per_unit * duty_rate_percent / 100",
            "landed_cost": "supplier_unit_cost + freight_per_unit + duty_per_unit + other_costs_per_unit",
            "contribution": "selling_price - channel_fee_per_unit - landed_cost_per_unit",
        },
        "exclusions": [
            "Returns and refunds",
            "Storage and fulfilment",
            "Advertising",
            "Taxes not explicitly included in supplied inputs",
            "Overhead and financing",
        ],
    }


def _inventory_reorder(inputs: dict[str, Any]) -> dict[str, Any]:
    on_hand = _d(inputs["on_hand_units"])
    daily_demand = _d(inputs["average_daily_demand"])
    lead_time = _d(inputs["supplier_lead_time_days"])
    safety_stock = _d(inputs["safety_stock_units"])
    inbound = _d(inputs.get("inbound_units", 0))
    moq = _d(inputs.get("minimum_order_quantity", 0))

    lead_time_demand = daily_demand * lead_time
    reorder_point = lead_time_demand + safety_stock
    inventory_position = on_hand + inbound
    reorder_gap = max(Decimal(0), reorder_point - inventory_position)
    suggested_order = max(reorder_gap, moq) if reorder_gap > 0 else Decimal(0)
    days_cover = (
        inventory_position / daily_demand if daily_demand > 0 else None
    )
    return {
        "calculation_type": "inventory-reorder",
        "sku": inputs["sku"],
        "lead_time_demand_units": _rounded(lead_time_demand),
        "reorder_point_units": _rounded(reorder_point),
        "inventory_position_units": _rounded(inventory_position),
        "days_of_cover": _rounded(days_cover),
        "reorder_gap_units": _rounded(reorder_gap),
        "minimum_order_quantity": _rounded(moq),
        "suggested_order_quantity": _rounded(suggested_order),
        "inbound_assumption": "Inbound units are treated as confirmed and usable.",
        "formula": "reorder_point = average_daily_demand * supplier_lead_time_days + safety_stock_units",
        "decision": "reorder_review_required" if reorder_gap > 0 else "at_or_above_reorder_point",
    }


def _pricing_promotion(inputs: dict[str, Any]) -> dict[str, Any]:
    landed = _d(inputs["unit_landed_cost"])
    current_price = _d(inputs["current_price"])
    marketplace_rate = _d(inputs["marketplace_fee_percent"]) / Decimal(100)
    payment_rate = _d(inputs.get("payment_fee_percent", 0)) / Decimal(100)
    discount_rate = _d(inputs.get("promo_discount_percent", 0)) / Decimal(100)
    target_margin = _d(inputs["target_contribution_margin_percent"]) / Decimal(100)
    total_fee_rate = marketplace_rate + payment_rate
    promo_price = current_price * (Decimal(1) - discount_rate)
    current_fee = current_price * total_fee_rate
    promo_fee = promo_price * total_fee_rate
    current_contribution = current_price - current_fee - landed
    promo_contribution = promo_price - promo_fee - landed
    current_margin = current_contribution / current_price * 100 if current_price > 0 else None
    promo_margin = promo_contribution / promo_price * 100 if promo_price > 0 else None
    price_floor_denominator = Decimal(1) - total_fee_rate - target_margin
    price_floor = (
        landed / price_floor_denominator
        if price_floor_denominator > 0 else None
    )
    volume_uplift = (
        (current_contribution / promo_contribution - 1) * 100
        if current_contribution > 0 and promo_contribution > 0 else None
    )
    return {
        "calculation_type": "pricing-promotion",
        "current_price": _rounded(current_price),
        "promotional_price": _rounded(promo_price),
        "total_variable_fee_percent": _rounded(total_fee_rate * 100),
        "current_contribution_per_unit": _rounded(current_contribution),
        "promotional_contribution_per_unit": _rounded(promo_contribution),
        "current_contribution_margin_percent": _rounded(current_margin),
        "promotional_contribution_margin_percent": _rounded(promo_margin),
        "target_margin_price_floor": _rounded(price_floor),
        "required_volume_uplift_percent_to_match_current_contribution": _rounded(volume_uplift),
        "volume_uplift_is_finite": volume_uplift is not None,
        "formula": "contribution = selling_price * (1 - total_variable_fee_rate) - unit_landed_cost",
        "exclusions": [
            "Advertising and acquisition spend",
            "Returns and refunds",
            "Fixed operating costs",
            "Taxes not included in supplied cost inputs",
        ],
    }



def _contribution_margin_waterfall(inputs: dict[str, Any]) -> dict[str, Any]:
    gross = _d(inputs["gross_sales"])
    discounts = _d(inputs["discounts"])
    refunds = _d(inputs["refunds"])
    cogs = _d(inputs["cost_of_goods_sold"])
    fulfilment = _d(inputs["fulfilment_costs"])
    channel_fees = _d(inputs["channel_fees"])
    advertising = _d(inputs.get("advertising_spend", 0))
    other_variable = _d(inputs.get("other_variable_costs", 0))
    net_sales = gross - discounts - refunds
    gross_profit = net_sales - cogs
    contribution_before_ads = gross_profit - fulfilment - channel_fees - other_variable
    contribution_after_ads = contribution_before_ads - advertising
    margin_before_ads = (
        contribution_before_ads / net_sales * Decimal(100)
        if net_sales > 0 else None
    )
    margin_after_ads = (
        contribution_after_ads / net_sales * Decimal(100)
        if net_sales > 0 else None
    )
    warnings: list[str] = []
    if discounts + refunds > gross:
        warnings.append("Discounts and refunds exceed gross sales; verify period and recognition basis.")
    if net_sales <= 0:
        warnings.append("Net sales are zero or negative; margin percentages are not meaningful.")
    return {
        "calculation_type": "contribution-margin-waterfall",
        "currency": str(inputs["currency"]).upper(),
        "gross_sales": _rounded(gross),
        "discounts": _rounded(discounts),
        "refunds": _rounded(refunds),
        "net_sales": _rounded(net_sales),
        "cost_of_goods_sold": _rounded(cogs),
        "gross_profit": _rounded(gross_profit),
        "fulfilment_costs": _rounded(fulfilment),
        "channel_fees": _rounded(channel_fees),
        "other_variable_costs": _rounded(other_variable),
        "contribution_before_advertising": _rounded(contribution_before_ads),
        "advertising_spend": _rounded(advertising),
        "contribution_after_advertising": _rounded(contribution_after_ads),
        "contribution_margin_before_advertising_percent": _rounded(margin_before_ads),
        "contribution_margin_after_advertising_percent": _rounded(margin_after_ads),
        "warnings": warnings,
        "formula": "net_sales = gross_sales - discounts - refunds; contribution_after_ads = net_sales - COGS - fulfilment - channel_fees - other_variable_costs - advertising_spend",
    }


def _customer_acquisition_cost(inputs: dict[str, Any]) -> dict[str, Any]:
    media = _d(inputs["media_spend"])
    agency = _d(inputs["agency_fees"])
    creative = _d(inputs["creative_cost"])
    tools = _d(inputs["measurement_tool_cost"])
    other = _d(inputs.get("other_acquisition_costs", 0))
    customers = _d(inputs["new_customers"])
    total = media + agency + creative + tools + other
    fully_loaded_cac = total / customers
    media_cac = media / customers
    return {
        "calculation_type": "customer-acquisition-cost",
        "currency": str(inputs["currency"]).upper(),
        "new_customers": int(customers),
        "media_spend": _rounded(media),
        "allocated_non_media_costs": _rounded(agency + creative + tools + other),
        "total_acquisition_cost": _rounded(total),
        "media_only_cac": _rounded(media_cac),
        "fully_loaded_cac": _rounded(fully_loaded_cac),
        "included_costs": ["Media", "Agency", "Creative", "Measurement tools", "Other supplied acquisition costs"],
        "formula": "fully_loaded_CAC = (media + agency + creative + measurement_tools + other_acquisition_costs) / new_customers",
        "warning": "CAC is comparable only when cohort, attribution, new-customer definition, and cost allocation basis match.",
    }


def _cohort_ltv(inputs: dict[str, Any]) -> dict[str, Any]:
    arpu = _d(inputs["monthly_arpu"])
    gross_margin = _d(inputs["gross_margin_percent"]) / Decimal(100)
    churn = _d(inputs["monthly_churn_percent"]) / Decimal(100)
    discount = _d(inputs.get("monthly_discount_rate_percent", 0)) / Decimal(100)
    decay = churn + discount
    monthly_contribution = arpu * gross_margin
    ltv = monthly_contribution / decay if decay > 0 else None
    warnings: list[str] = []
    if decay == 0:
        warnings.append("No churn or discount rate was supplied; finite contribution LTV cannot be estimated.")
    return {
        "calculation_type": "cohort-contribution-ltv",
        "currency": str(inputs["currency"]).upper(),
        "monthly_arpu": _rounded(arpu),
        "gross_margin_percent": _rounded(gross_margin * 100),
        "monthly_churn_percent": _rounded(churn * 100),
        "monthly_discount_rate_percent": _rounded(discount * 100),
        "monthly_contribution_per_customer": _rounded(monthly_contribution),
        "effective_monthly_decay_percent": _rounded(decay * 100),
        "estimated_contribution_ltv": _rounded(ltv),
        "warnings": warnings,
        "formula": "contribution_LTV = monthly_ARPU * gross_margin_rate / (monthly_churn_rate + monthly_discount_rate)",
        "model_assumption": "Steady-state geometric approximation with constant monthly ARPU, margin, churn, and discount rate.",
        "exclusions": ["Acquisition cost", "Servicing and support cost", "Refunds and returns not reflected in margin", "Expansion and contraction effects"],
    }

def calculate_skill(skill_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Return verified calculation context for the skills with deterministic models."""
    try:
        if skill_id == "landed-cost-margin-analysis":
            return _landed_cost(inputs)
        if skill_id == "inventory-reorder-review":
            return _inventory_reorder(inputs)
        if skill_id == "pricing-promotion-review":
            return _pricing_promotion(inputs)
        if skill_id == "contribution-margin-waterfall":
            return _contribution_margin_waterfall(inputs)
        if skill_id == "customer-acquisition-cost-review":
            return _customer_acquisition_cost(inputs)
        if skill_id == "cohort-ltv-estimator":
            return _cohort_ltv(inputs)
    except (ArithmeticError, InvalidOperation, KeyError, TypeError, ValueError):
        # Historical records may have pre-contract or malformed input; never break read APIs.
        return {}
    return {}
