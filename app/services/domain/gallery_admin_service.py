import glob
import os
import time

from flask import current_app, url_for

from ...extensions import db
from ...models.product import ProductSeries, WindowStyle

PDF_DIR = 'catalog_pdfs'
IMG_DIR = 'catalog_images'

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_IMG_BYTES = 5 * 1024 * 1024

IMG_EXTS = {'png', 'jpg', 'jpeg', 'webp'}

_IMG_SIGNATURES = (
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'\xff\xd8\xff', 'jpg'),
    (b'RIFF', 'webp'),
)


# ------------------------------------------------------------------ #
#  Paths / file helpers
# ------------------------------------------------------------------ #

def _dir(name: str) -> str:
    path = os.path.join(current_app.static_folder, name)
    os.makedirs(path, exist_ok=True)
    return path


def _has_file(f) -> bool:
    return f is not None and getattr(f, 'filename', '') not in ('', None)


def _read(f, limit: int) -> bytes:
    data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'File is too large (max {limit // (1024 * 1024)} MB)')
    if not data:
        raise ValueError('Uploaded file is empty')
    return data


def _remove_matching(pattern: str) -> None:
    for path in glob.glob(pattern):
        try:
            os.remove(path)
        except OSError:
            pass


def _detect_image_ext(data: bytes, filename: str) -> str:
    ext = os.path.splitext(filename or '')[1].lower().lstrip('.')
    if ext not in IMG_EXTS:
        raise ValueError('Image must be PNG, JPG or WEBP')
    for sig, kind in _IMG_SIGNATURES:
        if data.startswith(sig):
            if kind == 'webp' and data[8:12] != b'WEBP':
                continue
            return kind
    raise ValueError('Uploaded file is not a valid image')


def _save_image(f, stem: str) -> str:
    data = _read(f, MAX_IMG_BYTES)
    ext = _detect_image_ext(data, f.filename)
    folder = _dir(IMG_DIR)
    _remove_matching(os.path.join(folder, f'{stem}-*'))
    fname = f'{stem}-{int(time.time())}.{ext}'
    with open(os.path.join(folder, fname), 'wb') as out:
        out.write(data)
    return url_for('static', filename=f'{IMG_DIR}/{fname}')


def _save_pdf(f, stem: str) -> None:
    data = _read(f, MAX_PDF_BYTES)
    if not data.startswith(b'%PDF'):
        raise ValueError('Uploaded file is not a valid PDF')
    if os.path.splitext(f.filename or '')[1].lower() != '.pdf':
        raise ValueError('Brochure must be a .pdf file')
    with open(os.path.join(_dir(PDF_DIR), f'{stem}.pdf'), 'wb') as out:
        out.write(data)


def _delete_pdf(stem: str) -> None:
    _remove_matching(os.path.join(_dir(PDF_DIR), f'{stem}.pdf'))


def _delete_images(stem: str) -> None:
    _remove_matching(os.path.join(_dir(IMG_DIR), f'{stem}-*'))


# ------------------------------------------------------------------ #
#  Lookups (tenant scoped)
# ------------------------------------------------------------------ #

def get_series(tenant_id: int, series_id: int) -> ProductSeries | None:
    return ProductSeries.query.filter_by(id=series_id, tenant_id=tenant_id).first()


def get_style(tenant_id: int, style_id: int) -> WindowStyle | None:
    style = WindowStyle.query.filter_by(id=style_id).first()
    if not style:
        return None
    if not get_series(tenant_id, style.series_id):
        return None
    return style


# ------------------------------------------------------------------ #
#  Series
# ------------------------------------------------------------------ #

def create_series(tenant_id: int, name: str, material: str | None = None,
                  description: str | None = None,
                  image_file=None, pdf_file=None) -> ProductSeries:
    name = (name or '').strip()
    if not name:
        raise ValueError('Series name is required')

    series = ProductSeries(
        tenant_id=tenant_id,
        name=name[:120],
        material=(material or 'Aluminium').strip()[:50],
        description=(description or '').strip()[:400] or None,
        is_active=True,
    )
    db.session.add(series)
    db.session.flush()

    try:
        if _has_file(image_file):
            series.thumbnail = _save_image(image_file, f'series-{series.id}')
        if _has_file(pdf_file):
            _save_pdf(pdf_file, f'series-{series.id}')
    except ValueError:
        db.session.rollback()
        raise

    db.session.commit()
    return series


def update_series(tenant_id: int, series_id: int, name: str, material: str | None,
                  description: str | None, image_file=None, pdf_file=None,
                  remove_pdf: bool = False) -> ProductSeries:
    series = get_series(tenant_id, series_id)
    if not series:
        raise LookupError('Series not found')

    name = (name or '').strip()
    if not name:
        raise ValueError('Series name is required')

    series.name = name[:120]
    series.material = (material or 'Aluminium').strip()[:50]
    series.description = (description or '').strip()[:400] or None

    if _has_file(image_file):
        series.thumbnail = _save_image(image_file, f'series-{series.id}')
    if _has_file(pdf_file):
        _save_pdf(pdf_file, f'series-{series.id}')
    elif remove_pdf:
        _delete_pdf(f'series-{series.id}')

    db.session.commit()
    return series


def delete_series(tenant_id: int, series_id: int) -> None:
    series = get_series(tenant_id, series_id)
    if not series:
        raise LookupError('Series not found')

    for style in series.styles.all():
        _delete_pdf(f'style-{style.id}')
        _delete_images(f'style-{style.id}')

    _delete_pdf(f'series-{series.id}')
    _delete_images(f'series-{series.id}')

    db.session.delete(series)
    db.session.commit()


# ------------------------------------------------------------------ #
#  Styles
# ------------------------------------------------------------------ #

def create_style(tenant_id: int, series_id: int, name: str, panels: int = 1,
                 image_file=None, pdf_file=None) -> WindowStyle:
    series = get_series(tenant_id, series_id)
    if not series:
        raise LookupError('Series not found')

    name = (name or '').strip()
    if not name:
        raise ValueError('Product name is required')
    if panels is None or panels < 1:
        raise ValueError('Panels must be at least 1')

    next_order = (db.session.query(db.func.coalesce(db.func.max(WindowStyle.sort_order), 0))
                  .filter(WindowStyle.series_id == series.id).scalar() or 0) + 1

    style = WindowStyle(
        series_id=series.id,
        name=name[:120],
        panels=int(panels),
        sort_order=next_order,
    )
    db.session.add(style)
    db.session.flush()

    try:
        if _has_file(image_file):
            style.image = _save_image(image_file, f'style-{style.id}')
        if _has_file(pdf_file):
            _save_pdf(pdf_file, f'style-{style.id}')
    except ValueError:
        db.session.rollback()
        raise

    db.session.commit()
    return style


def update_style(tenant_id: int, style_id: int, name: str, panels: int,
                 image_file=None, pdf_file=None,
                 remove_pdf: bool = False, remove_image: bool = False) -> WindowStyle:
    style = get_style(tenant_id, style_id)
    if not style:
        raise LookupError('Product not found')

    name = (name or '').strip()
    if not name:
        raise ValueError('Product name is required')
    if panels is None or panels < 1:
        raise ValueError('Panels must be at least 1')

    style.name = name[:120]
    style.panels = int(panels)

    if _has_file(image_file):
        style.image = _save_image(image_file, f'style-{style.id}')
    elif remove_image:
        _delete_images(f'style-{style.id}')
        style.image = None

    if _has_file(pdf_file):
        _save_pdf(pdf_file, f'style-{style.id}')
    elif remove_pdf:
        _delete_pdf(f'style-{style.id}')

    db.session.commit()
    return style


def delete_style(tenant_id: int, style_id: int) -> None:
    style = get_style(tenant_id, style_id)
    if not style:
        raise LookupError('Product not found')

    _delete_pdf(f'style-{style.id}')
    _delete_images(f'style-{style.id}')

    db.session.delete(style)
    db.session.commit()
