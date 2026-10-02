SRC_QUOTATION = "quotation"
SRC_PROJECT = "project"
SRC_TENANT = "tenant"
SRC_LLM = "llm"
SRC_ITEM_ROW = "item_row"
SRC_CHARGE_ROW = "charge_row"

SCALAR_TOKENS = {
    "company_name": (SRC_TENANT, "tenant.name"),
    "company_email": (SRC_TENANT, "tenant.contact_email"),

    "customer_name": (SRC_PROJECT, "project.customer_name"),
    "project_address": (SRC_PROJECT, "project.address"),

    "quotation_number": (SRC_QUOTATION, "quotation.quotation_number"),
    "quotation_version": (SRC_QUOTATION, "quotation.quotation_version"),
    "quotation_date": (SRC_QUOTATION, "quotation.created_at"),
    "validity_date": (SRC_QUOTATION, "quotation.validity_date"),
    "payment_terms": (SRC_QUOTATION, "quotation.payment_terms_template"),
    "subtotal": (SRC_QUOTATION, "quotation.subtotal"),
    "discount_pct": (SRC_QUOTATION, "quotation.discount_pct"),
    "discount_amount": (SRC_QUOTATION, "quotation.discount_amount"),
    "tax_rate": (SRC_QUOTATION, "quotation.tax_rate"),
    "tax_amount": (SRC_QUOTATION, "quotation.tax_amount"),
    "grand_total": (SRC_QUOTATION, "quotation.grand_total"),
    "installation_charge": (SRC_QUOTATION, "quotation.installation_charge"),
    "transport_charge": (SRC_QUOTATION, "quotation.transport_charge"),
    "amc_tier": (SRC_QUOTATION, "quotation.amc_offer_tier"),
    "amc_price": (SRC_QUOTATION, "quotation.amc_price"),
    "warranty_months": (SRC_QUOTATION, "quotation.warranty_months"),
    "warranty_terms": (SRC_QUOTATION, "quotation.warranty_terms_text"),

    "executive_summary": (SRC_LLM, "copy.executive_summary"),
    "scope_of_work": (SRC_LLM, "copy.scope_of_work"),
    "commercial_notes": (SRC_LLM, "copy.commercial_notes"),
    "next_steps": (SRC_LLM, "copy.next_steps"),
}

ITEM_ROW_TOKENS = {
    "item_no": (SRC_ITEM_ROW, "line_items[].index"),
    "item_label": (SRC_ITEM_ROW, "line_items[].label"),
    "item_material": (SRC_ITEM_ROW, "line_items[].material"),
    "item_size": (SRC_ITEM_ROW, "line_items[].width_mm x height_mm"),
    "item_qty": (SRC_ITEM_ROW, "line_items[].qty"),
    "item_amount": (SRC_ITEM_ROW, "line_items[].amount"),
}

CHARGE_ROW_TOKENS = {
    "charge_label": (SRC_CHARGE_ROW, "charges[].label"),
    "charge_details": (SRC_CHARGE_ROW, "charges[].details"),
    "charge_amount": (SRC_CHARGE_ROW, "charges[].amount"),
}

ALL_TOKENS = {**SCALAR_TOKENS, **ITEM_ROW_TOKENS, **CHARGE_ROW_TOKENS}


def placeholder(name: str) -> str:
    return "{{" + name + "}}"
