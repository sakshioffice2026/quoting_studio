from ...extensions import db
from ...repositories import requirement_template_repo, preliminary_selection_repo


def _coerce_for_field(field_name: str, value):
    """shortlisted_ranges is stored as text; chip lists get joined into a readable string.
    rough_opening_* / indicative_price_* are numeric."""
    if field_name == 'shortlisted_ranges':
        if isinstance(value, list):
            return ', '.join(str(v) for v in value)
        return str(value)

    if field_name in ('rough_opening_doors', 'rough_opening_windows'):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if field_name in ('indicative_price_min', 'indicative_price_max'):
        # slider answers come in as budget bands ('₹', '₹₹', '₹₹₹') -> rough numeric bands
        band_map = {'₹': 200000, '₹₹': 500000, '₹₹₹': 1000000}
        if isinstance(value, str) and value in band_map:
            return band_map[value]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return value


def build_mapped_fields(response) -> dict:
    """Pure translation: template answers -> PreliminarySelection field values.
    Does not touch the DB. Safe to call before a Project/PreliminarySelection exists."""
    ids = response.project_type_ids or ([response.project_type_id] if response.project_type_id else [])
    questions = requirement_template_repo.list_questions_for_types(ids)

    fields = {}
    for q in questions:
        if not q.maps_to_field:
            continue
        raw_value = response.get_answer(q.question_key)
        if raw_value in (None, '', []):
            continue
        fields[q.maps_to_field] = _coerce_for_field(q.maps_to_field, raw_value)

    tags = [pt.tag for pt in response.project_types if pt.tag]
    if tags:
        existing = fields.get('shortlisted_ranges', '')
        tag_str = ' '.join(f'[{t}]' for t in tags)
        fields['shortlisted_ranges'] = f'{tag_str} {existing}'.strip() if existing else tag_str

    return fields


def map_to_preliminary_selection(tenant_id: int, response):
    """Called on customer submit. PreliminarySelection requires a Project, which only
    exists once a rep has qualified the lead (see preliminary_selection_service).
    So: if a PreliminarySelection already exists for this lead, update it now.
    Otherwise, just leave the mapped answers on the TemplateResponse (already saved) —
    the rep's 'Convert to Preliminary Selection' action (start_preliminary_selection)
    will pull build_mapped_fields() at that point instead."""
    fields = build_mapped_fields(response)

    presel = preliminary_selection_repo.get_by_lead(tenant_id, response.lead_id)
    if presel:
        preliminary_selection_repo.update(presel, **fields)
        db.session.commit()
    return presel
