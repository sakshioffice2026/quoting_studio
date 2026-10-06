from __future__ import annotations

from decimal import Decimal

DATE_FMT = "%d %B %Y"


def _money(value, symbol: str = "$") -> str:
    try:
        return f"{symbol}{Decimal(str(value or 0)):,.2f}"
    except Exception:
        return f"{symbol}0.00"


def _date(value) -> str:
    if not value:
        return ""
    try:
        return value.strftime(DATE_FMT)
    except Exception:
        return str(value)


def _pct(value) -> str:
    try:
        return f"{Decimal(str(value or 0)):.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "0"


def _tax_label(rate) -> str:
    try:
        return f"{(Decimal(str(rate or 0)) * 100):.2f}".rstrip("0").rstrip(".") + "%"
    except Exception:
        return "0%"


def _size(item: dict) -> str:
    w = item.get("width_mm")
    h = item.get("height_mm")
    if w and h:
        try:
            return f"{int(w)} x {int(h)} mm"
        except (TypeError, ValueError):
            return f"{w} x {h} mm"
    return "-"


def _build_item_rows(quotation, symbol: str) -> list[dict]:
    rows = []
    for idx, item in enumerate(quotation.line_items, start=1):
        rows.append(
            {
                "item_no": str(idx),
                "item_label": str(item.get("label") or f"Item {idx}"),
                "item_material": str(item.get("material") or "-"),
                "item_size": _size(item),
                "item_qty": str(item.get("qty") or 1),
                "item_amount": _money(item.get("amount"), symbol),
            }
        )
    return rows


def _build_charge_rows(quotation, symbol: str) -> list[dict]:
    rows = []

    if quotation.installation_charge:
        rows.append(
            {
                "charge_label": "Installation Charges",
                "charge_details": "Fitting and on-site installation",
                "charge_amount": _money(quotation.installation_charge, symbol),
            }
        )

    if quotation.transport_charge:
        rows.append(
            {
                "charge_label": "Transport Charges",
                "charge_details": "Delivery to site",
                "charge_amount": _money(quotation.transport_charge, symbol),
            }
        )

    for charge in quotation.other_charges:
        if isinstance(charge, dict):
            label = charge.get("label") or "Other Charges"
            amount = charge.get("amount")
        else:
            label = getattr(charge, "label", "Other Charges")
            amount = getattr(charge, "amount", 0)
        rows.append(
            {
                "charge_label": str(label),
                "charge_details": "-",
                "charge_amount": _money(amount, symbol),
            }
        )

    if quotation.amc_offered:
        rows.append(
            {
                "charge_label": f"AMC - {quotation.amc_offer_tier or 'Standard'}",
                "charge_details": "Annual maintenance contract",
                "charge_amount": _money(quotation.amc_price, symbol) if quotation.amc_price else "-",
            }
        )

    if quotation.warranty_months:
        rows.append(
            {
                "charge_label": "Warranty",
                "charge_details": quotation.warranty_terms_text
                or f"{quotation.warranty_months} months standard warranty",
                "charge_amount": "Included",
            }
        )

    return rows


def _count_openings(quotation) -> dict:
    windows = 0
    doors = 0
    for item in quotation.line_items:
        qty = int(item.get("qty") or 1)
        if "door" in str(item.get("label") or "").lower():
            doors += qty
        else:
            windows += qty
    return {"windows": windows, "doors": doors}


def build_proposal_context(quotation, project, tenant, currency_symbol: str | None = None) -> dict:
    """
    Returns:
      scalars      -> {token_name: str}  (all non-LLM tokens)
      item_rows    -> list of dict for the line-item table
      charge_rows  -> list of dict for the charges table
      llm_input    -> facts handed to the LLM for writing copy (no price authority)
    """
    if not currency_symbol:
        currency_symbol = tenant.currency_symbol if tenant is not None else "$"
    scalars = {
        "company_name": getattr(tenant, "name", "") or "",
        "company_email": getattr(tenant, "contact_email", "") or "",

        "customer_name": getattr(project, "customer_name", "") or "",
        "project_address": getattr(project, "address", "") or "",

        "quotation_number": quotation.quotation_number or "",
        "quotation_version": str(quotation.quotation_version or 1),
        "quotation_date": _date(quotation.created_at),
        "validity_date": _date(quotation.validity_date),
        "payment_terms": quotation.payment_terms_template or "-",

        "subtotal": _money(quotation.subtotal, currency_symbol),
        "discount_pct": _pct(quotation.discount_pct),
        "discount_amount": _money(quotation.discount_amount, currency_symbol),
        "tax_rate": _tax_label(quotation.tax_rate),
        "tax_amount": _money(quotation.tax_amount, currency_symbol),
        "grand_total": _money(quotation.grand_total, currency_symbol),

        "installation_charge": _money(quotation.installation_charge, currency_symbol),
        "transport_charge": _money(quotation.transport_charge, currency_symbol),
        "amc_tier": (quotation.amc_offer_tier or "") if quotation.amc_offered else "Not offered",
        "amc_price": _money(quotation.amc_price, currency_symbol) if quotation.amc_offered and quotation.amc_price else "",
        "warranty_months": str(quotation.warranty_months or ""),
        "warranty_terms": quotation.warranty_terms_text or "",
    }

    item_rows = _build_item_rows(quotation, currency_symbol)
    charge_rows = _build_charge_rows(quotation, currency_symbol)
    openings = _count_openings(quotation)

    materials = sorted({r["item_material"] for r in item_rows if r["item_material"] not in ("", "-")})

    llm_input = {
        "company_name": scalars["company_name"],
        "customer_name": scalars["customer_name"],
        "project_address": scalars["project_address"],
        "quotation_number": scalars["quotation_number"],
        "validity_date": scalars["validity_date"],
        "window_count": openings["windows"],
        "door_count": openings["doors"],
        "materials": materials,
        "items": [
            {
                "label": r["item_label"],
                "material": r["item_material"],
                "size": r["item_size"],
                "qty": r["item_qty"],
            }
            for r in item_rows
        ],
        "has_installation": bool(quotation.installation_charge),
        "has_transport": bool(quotation.transport_charge),
        "amc_offered": bool(quotation.amc_offered),
        "amc_tier": quotation.amc_offer_tier or "",
        "warranty_months": quotation.warranty_months or 0,
        "payment_terms": scalars["payment_terms"],
    }

    return {
        "scalars": scalars,
        "item_rows": item_rows,
        "charge_rows": charge_rows,
        "llm_input": llm_input,
    }
