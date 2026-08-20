"""
Optional DWG output.

ezdxf writes DXF natively. To produce a true .dwg file (as requested for
fabrication handoff), we convert the generated DXF using ODA File Converter
if it's installed. Otherwise DXF is served (every CAD package reads DXF).
"""
import os
import shutil
import tempfile
import subprocess
import logging

logger = logging.getLogger(__name__)


# Set at import time so API can probe without calling find_oda() on every request
ODA_AVAILABLE: bool = False   # updated below after find_oda is defined

def find_oda() -> str | None:
    candidates = [
        r'C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe',
        r'C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe',
        r'C:\Program Files\ODA\ODAFileConverter 26.4.0\ODAFileConverter.exe',
        '/usr/bin/ODAFileConverter',
        '/opt/ODA/ODAFileConverter/ODAFileConverter',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which('ODAFileConverter')


def dxf_to_dwg(dxf_bytes: bytes, version: str = 'ACAD2018') -> bytes | None:
    """
    Convert DXF bytes to DWG bytes via ODA File Converter.
    Returns DWG bytes, or None if ODA is unavailable / conversion fails.
    """
    oda = find_oda()
    if not oda:
        logger.info('ODA File Converter not installed — DWG conversion skipped')
        return None

    try:
        in_dir  = tempfile.mkdtemp(prefix='qs_dxf_in_')
        out_dir = tempfile.mkdtemp(prefix='qs_dwg_out_')
        dxf_path = os.path.join(in_dir, 'drawing.dxf')
        with open(dxf_path, 'wb') as f:
            f.write(dxf_bytes)

        # ODAFileConverter <in> <out> <ver> <DWG> <recurse> <audit>
        cmd = [oda, in_dir, out_dir, version, 'DWG', '0', '1']
        r = subprocess.run(cmd, timeout=60, capture_output=True, text=True)
        logger.info('ODA DWG conversion exit=%d', r.returncode)

        dwg_path = os.path.join(out_dir, 'drawing.dwg')
        if os.path.exists(dwg_path):
            with open(dwg_path, 'rb') as f:
                dwg = f.read()
            shutil.rmtree(in_dir, ignore_errors=True)
            shutil.rmtree(out_dir, ignore_errors=True)
            logger.info('DWG produced: %d bytes', len(dwg))
            return dwg
        logger.warning('ODA ran but no DWG output found')
    except subprocess.TimeoutExpired:
        logger.warning('ODA DWG conversion timed out')
    except Exception as exc:
        logger.exception('DWG conversion error: %s', exc)
    return None


ODA_AVAILABLE = find_oda() is not None