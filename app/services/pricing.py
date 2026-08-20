import logging
from decimal import Decimal, InvalidOperation
from ..models import PricingRule, OpenerPricingRule, GlazingPricingRule

logger = logging.getLogger(__name__)

_DEFAULT_FRAME = {
    'Aluminium': Decimal('3.20'),
    'PVCu':      Decimal('1.80'),
    'Timber':    Decimal('2.40'),
    'Steel':     Decimal('4.50'),
}
_DEFAULT_GLASS   = Decimal('95.00')
_DEFAULT_FITTING = Decimal('140.00')

# Hardware option surcharges (added on top of opener hardware)
_HARDWARE_COST = {
    'Handle': {
        'Standard Cockspur': Decimal('8'),  'Espagnolette': Decimal('22'),
        'Monkey Tail': Decimal('28'),       'Cranked': Decimal('14'),
        'Pad': Decimal('12'),
    },
    'Sash Lift':  {'Hook Lift': Decimal('9'), 'Flush Ring Lift': Decimal('12'), 'Bar Lift': Decimal('15')},
    'Sash Ring':  {'Standard Ring': Decimal('6'), 'Heritage Ring': Decimal('11')},
    'Travel Restrict': {'Restrictor Hinge': Decimal('14'), 'Cable Restrictor': Decimal('9'), 'Child Lock': Decimal('7')},
    'Ventilation':{'Trickle Vent 4000': Decimal('18'), 'Trickle Vent 5000': Decimal('24'), 'Acoustic Vent': Decimal('38')},
}
_HARDWARE_FINISH_UPLIFT = {
    'White': Decimal('0'), 'Chrome': Decimal('8'), 'Satin Chrome': Decimal('10'),
    'Gold': Decimal('16'), 'Black': Decimal('6'), 'Antique Brass': Decimal('14'),
}
# Glazing bar cost per bar (Georgian bars)
_GLAZING_BAR_COST = Decimal('12.50')


# Per-category hardware base cost when any option is selected
_HW_CAT_COST = {
    'Catch': Decimal('18'), 'Sash Lift': Decimal('12'), 'Sash Ring': Decimal('9'),
    'Travel Restrictor': Decimal('16'), 'Ventilation': Decimal('22'),
}

def _hardware_extras_cost(design: dict) -> tuple:
    """Compute (hardware_cost, extras_cost, bars_cost) from a design dict.
    Handles both legacy hardware {cat:'name'} and new {cat:{sel,qty}} structures,
    plus preset extras and free-form customExtras."""
    hw_cost = Decimal('0')
    extras  = Decimal('0')
    bars    = Decimal('0')
    if not design:
        return hw_cost, extras, bars
    try:
        hardware = design.get('hardware', {}) or {}
        for cat, val in hardware.items():
            if cat.startswith('_'):
                continue
            sel = val.get('sel') if isinstance(val, dict) else val
            if not sel or sel == 'None':
                continue
            hw_cost += _HW_CAT_COST.get(cat, Decimal('12'))

        # preset extras
        for key, item in (design.get('extras', {}) or {}).items():
            try:
                extras += Decimal(str(item.get('price', 0))) * Decimal(str(item.get('qty', 1)))
            except Exception:
                pass

        # custom extras
        for c in (design.get('customExtras', []) or []):
            try:
                extras += Decimal(str(c.get('price', 0))) * Decimal(str(c.get('qty', 1)))
            except Exception:
                pass

        # glazing bars
        total_bars = sum(len(p.get('glazingBars', []) or []) for p in design.get('panes', []))
        bars = _GLAZING_BAR_COST * Decimal(str(total_bars))
    except Exception as exc:
        logger.warning('hardware/extras pricing error: %s', exc)
    return hw_cost, extras, bars


def calculate_price(window, panes, tenant_id: int, design: dict = None) -> dict:
    """
    Return a pricing breakdown dict for one window.
    Falls back to built-in defaults if tenant rules are missing.
    Never raises — returns zeros on unexpected error.
    """
    try:
        W = int(window.width_mm)
        H = int(window.height_mm)
        area_m2     = Decimal(str((W * H) / 1_000_000))
        perimeter_m = Decimal(str(2 * (W + H) / 1000))

        # ---- material rule -------------------------------------------
        rule = PricingRule.query.filter_by(
            tenant_id=tenant_id, material=window.material, is_active=True
        ).first()

        frame_rate = Decimal(str(rule.frame_cost_per_metre)) if rule else _DEFAULT_FRAME.get(window.material, Decimal('3.20'))
        glass_rate = Decimal(str(rule.glass_cost_per_m2))   if rule else _DEFAULT_GLASS
        fitting    = Decimal(str(rule.fitting_fixed))        if rule else _DEFAULT_FITTING

        frame_cost = frame_rate * perimeter_m

        # ---- hardware ------------------------------------------------
        hardware_cost = Decimal('0')
        for pane in panes:
            try:
                opener_rule = OpenerPricingRule.query.filter_by(
                    tenant_id=tenant_id, opener_type=pane.opener_type, is_active=True
                ).first()
                if opener_rule:
                    hardware_cost += Decimal(str(opener_rule.hardware_cost))
            except Exception as exc:
                logger.warning('Hardware pricing error for opener=%s: %s', pane.opener_type, exc)

        # ---- glazing cost — per pane ----
        # Priority 1: the pane's glazing matches a GlassUnit CODE with an explicit
        #             £/m² supply rate (new Glass Library — UK trade convention).
        # Priority 2: legacy GlazingPricingRule multiplier on the base glass rate.
        from ..models import GlassUnit
        glass_area_m2 = Decimal(str(window.width_mm * window.height_mm / 1_000_000))
        glass_base    = glass_rate    # £/m² base rate (already resolved above)
        glass_cost    = Decimal('0')
        for pane in panes:
            try:
                # solid door panels carry no glazing cost
                if getattr(pane, 'infill', 'glass') == 'panel':
                    continue
                pane_area = glass_area_m2 * Decimal(str(pane.w_norm * pane.h_norm))
                gtype     = pane.glazing_type

                # 1) glass-library code with explicit £/m²
                unit = (GlassUnit.query
                        .filter_by(tenant_id=tenant_id, code=gtype, is_active=True)
                        .first()) if tenant_id else None
                if unit and unit.price_per_m2 is not None:
                    glass_cost += Decimal(str(unit.price_per_m2)) * pane_area
                    continue

                # 2) legacy multiplier rule keyed by glazing name
                mult = Decimal('0')
                glazing_rule = (GlazingPricingRule.query
                                .filter_by(tenant_id=tenant_id, glazing_type=gtype, is_active=True)
                                .first()) if tenant_id else None
                if glazing_rule:
                    mult = Decimal(str(glazing_rule.cost_multiplier))
                glass_cost += glass_base * pane_area * (1 + mult)
            except Exception as exc:
                logger.warning('Glazing pricing error for type=%s: %s',
                               getattr(pane, 'glazing_type', '?'), exc)
                glass_cost += glass_base * pane_area

        # ---- hardware options + extras + glazing bars (from design) --
        hw_opt_cost, extras_cost, bars_cost = _hardware_extras_cost(design)
        hardware_cost += hw_opt_cost + bars_cost

        total = frame_cost + glass_cost + hardware_cost + extras_cost + fitting

        result = {
            'frame':       float(round(frame_cost + glass_cost, 2)),
            'frame_glass': float(round(frame_cost + glass_cost, 2)),
            'hardware':    float(round(hardware_cost, 2)),
            'extras':      float(round(extras_cost, 2)),
            'fitting':     float(round(fitting, 2)),
            'total':       float(round(total, 2)),
        }
        logger.debug('Pricing: window=%s material=%s total=%.2f',
                      getattr(window, 'id', '?'), window.material, result['total'])
        return result

    except (InvalidOperation, ValueError, TypeError) as exc:
        logger.error('Pricing calculation error (bad value): %s', exc)
        return {'frame': 0.0, 'frame_glass': 0.0, 'hardware': 0.0, 'extras': 0.0, 'fitting': 0.0, 'total': 0.0}
    except Exception as exc:
        logger.exception('Unexpected pricing error: %s', exc)
        return {'frame': 0.0, 'frame_glass': 0.0, 'hardware': 0.0, 'extras': 0.0, 'fitting': 0.0, 'total': 0.0}