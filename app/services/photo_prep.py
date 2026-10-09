import io
import os
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 2400
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 80_000_000
JPEG_QUALITY = 90
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF', 'MPO'}


class PhotoError(ValueError):
    pass


def prepare_photo(stream, dest_dir, prefix):
    raw = stream.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise PhotoError('Empty file')
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PhotoError('Photo is too large (max 15 MB)')

    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = probe.format
        size = probe.size
        probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise PhotoError('File is not a valid image')

    if fmt not in ALLOWED_FORMATS:
        raise PhotoError('Unsupported image format')
    if size[0] * size[1] > MAX_PIXELS:
        raise PhotoError('Image dimensions are too large')

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise PhotoError('Image could not be decoded')

    img = ImageOps.exif_transpose(img)

    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        rgba = img.convert('RGBA')
        flat = Image.new('RGB', rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        img = flat
    else:
        img = img.convert('RGB')

    orig_w, orig_h = img.size
    scale = min(1.0, MAX_SIDE / float(max(orig_w, orig_h)))
    if scale < 1.0:
        img = img.resize(
            (max(1, round(orig_w * scale)), max(1, round(orig_h * scale))),
            Image.Resampling.LANCZOS,
        )

    os.makedirs(dest_dir, exist_ok=True)
    filename = f'{prefix}-{uuid.uuid4().hex[:8]}.jpg'
    img.save(os.path.join(dest_dir, filename), 'JPEG', quality=JPEG_QUALITY, optimize=True)

    return {
        'filename': filename,
        'width': img.size[0],
        'height': img.size[1],
        'scale': scale,
        'orig_width': orig_w,
        'orig_height': orig_h,
    }
