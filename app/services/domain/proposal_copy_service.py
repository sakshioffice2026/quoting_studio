from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"

COPY_TOOL_NAME = "submit_proposal_copy"

COPY_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "scope_of_work": {"type": "string"},
        "commercial_notes": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["executive_summary", "scope_of_work", "commercial_notes", "next_steps"],
}

SYSTEM_PROMPT = (
    "You write proposal copy for a windows and doors manufacturer and installer. "
    "Use only the facts provided. Never state, estimate or invent any price, "
    "cost, discount, tax, dimension, delivery date or technical specification "
    "that is not in the provided facts. Do not use currency symbols or amounts. "
    "Tone: professional, clear, concise. "
    "executive_summary: 2 to 3 sentences. "
    "scope_of_work: 3 to 5 sentences covering supply, installation and finishing "
    "only where the facts say they are included. "
    "commercial_notes: 1 to 2 sentences about validity, payment terms and warranty "
    "using only the provided values. "
    "next_steps: 3 to 5 short action items."
)

CURRENCY_RE = re.compile(r"[$€£₹]\s?\d|\d\s?(?:USD|EUR|GBP|INR)\b", re.IGNORECASE)

LIMITS = {
    "executive_summary": 900,
    "scope_of_work": 1500,
    "commercial_notes": 700,
}


# ------------------------------------------------------------------ #
#  Fallback (no LLM)
# ------------------------------------------------------------------ #

def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def build_fallback_copy(llm_input: dict) -> dict:
    windows = int(llm_input.get("window_count") or 0)
    doors = int(llm_input.get("door_count") or 0)
    materials = llm_input.get("materials") or []

    parts = []
    if windows:
        parts.append(_plural(windows, "window"))
    if doors:
        parts.append(_plural(doors, "door"))
    scope_count = " and ".join(parts) if parts else "the agreed windows and doors"

    customer = llm_input.get("customer_name") or "you"
    address = llm_input.get("project_address") or ""
    company = llm_input.get("company_name") or "We"

    material_text = ""
    if materials:
        material_text = f" in {', '.join(materials)}"

    summary = (
        f"{company} is pleased to present this proposal for {scope_count}{material_text}"
        f"{' at ' + address if address else ''}. "
        f"This quotation has been prepared for {customer} based on the approved requirements."
    )

    scope_bits = [f"Supply of {scope_count}{material_text} as listed in the specification."]
    if llm_input.get("has_installation"):
        scope_bits.append("On-site fitting and installation by our trained team is included.")
    if llm_input.get("has_transport"):
        scope_bits.append("Delivery of all items to the project site is included.")
    if llm_input.get("amc_offered"):
        tier = llm_input.get("amc_tier") or "selected"
        scope_bits.append(f"An annual maintenance contract ({tier}) is offered with this proposal.")
    scope = " ".join(scope_bits)

    notes_bits = []
    if llm_input.get("validity_date"):
        notes_bits.append(f"This quotation is valid until {llm_input['validity_date']}.")
    if llm_input.get("payment_terms") and llm_input["payment_terms"] != "-":
        notes_bits.append(f"Payment terms: {llm_input['payment_terms']}.")
    if llm_input.get("warranty_months"):
        notes_bits.append(f"A {llm_input['warranty_months']}-month warranty applies.")
    notes = " ".join(notes_bits)

    steps = [
        "Review the specification and pricing in this proposal.",
        "Confirm any changes to quantities, sizes or materials.",
        "Approve the quotation to proceed to order confirmation.",
        "Schedule site survey or installation as agreed.",
    ]

    return {
        "executive_summary": summary,
        "scope_of_work": scope,
        "commercial_notes": notes,
        "next_steps": steps,
        "source": "fallback",
    }


# ------------------------------------------------------------------ #
#  Validation
# ------------------------------------------------------------------ #

def _clean_text(value, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def validate_copy(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None

    out = {}
    for key, limit in LIMITS.items():
        text = _clean_text(raw.get(key), limit)
        if not text:
            return None
        if CURRENCY_RE.search(text):
            logger.warning("LLM copy rejected: currency amount found in %s", key)
            return None
        out[key] = text

    steps = raw.get("next_steps")
    if not isinstance(steps, list) or not steps:
        return None
    clean_steps = []
    for s in steps[:6]:
        t = _clean_text(s, 200)
        if not t or CURRENCY_RE.search(t):
            return None
        clean_steps.append(t)
    out["next_steps"] = clean_steps

    return out


# ------------------------------------------------------------------ #
#  LLM call
# ------------------------------------------------------------------ #

def _call_llm(llm_input: dict) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import json
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("PROPOSAL_LLM_MODEL", DEFAULT_MODEL)

        response = client.messages.create(
            model=model,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            tools=[
                {
                    "name": COPY_TOOL_NAME,
                    "description": "Submit the proposal copy sections.",
                    "input_schema": COPY_TOOL_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": COPY_TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": "Facts for this proposal (JSON):\n" + json.dumps(llm_input, ensure_ascii=False),
                }
            ],
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == COPY_TOOL_NAME:
                return block.input
    except Exception as exc:
        logger.exception("Proposal LLM call failed: %s", exc)

    return None


# ------------------------------------------------------------------ #
#  Public API
# ------------------------------------------------------------------ #

def generate_proposal_copy(llm_input: dict, use_llm: bool = True) -> dict:
    """
    Returns dict with executive_summary, scope_of_work, commercial_notes,
    next_steps (list) and source ('llm' or 'fallback').
    """
    if use_llm:
        raw = _call_llm(llm_input)
        valid = validate_copy(raw) if raw else None
        if valid:
            valid["source"] = "llm"
            return valid

    return build_fallback_copy(llm_input)
