"""Shared server-side validation helpers.

Every check_* function returns an error message (str) or None when valid.
"""
import re

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')
PHONE_RE = re.compile(r'^\+?[0-9][0-9\s\-()]{5,19}$')


def _clean(value):
    return (value or '').strip()


def check_text(value, label, *, required=False, min_len=0, max_len=255, letters=False):
    value = _clean(value)
    if not value:
        return f'{label} is required.' if required else None
    if min_len and len(value) < min_len:
        return f'{label} must be at least {min_len} characters.'
    if len(value) > max_len:
        return f'{label} must be at most {max_len} characters.'
    if letters and not any(ch.isalpha() for ch in value):
        return f'{label} must contain letters.'
    return None


def check_email(value, label='Email', *, required=False):
    value = _clean(value)
    if not value:
        return f'{label} is required.' if required else None
    if len(value) > 254 or not EMAIL_RE.match(value):
        return f'Enter a valid {label.lower()}, e.g. name@company.com.'
    return None


def check_phone(value, label='Phone', *, required=False):
    value = _clean(value)
    if not value:
        return f'{label} is required.' if required else None
    digits = re.sub(r'\D', '', value)
    if not PHONE_RE.match(value) or not 7 <= len(digits) <= 15:
        return f'Enter a valid {label.lower()} number (7-15 digits, may start with +).'
    return None


def check_choice(value, label, choices, *, required=False):
    value = _clean(value)
    if not value:
        return f'Select a {label.lower()}.' if required else None
    if value not in choices:
        return f'Invalid {label.lower()} selected.'
    return None


def check_password(password, label='Password'):
    if not password:
        return f'{label} is required.'
    if len(password) < 8:
        return f'{label} must be at least 8 characters.'
    if len(password) > 128:
        return f'{label} must be at most 128 characters.'
    if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
        return f'{label} must include at least one letter and one number.'
    return None
