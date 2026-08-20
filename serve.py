"""
Quoting Studio — production entry point for IIS + HttpPlatformHandler.

IIS assigns a random internal port via the PORT env var (%HTTP_PLATFORM_PORT%)
and proxies public traffic to it. This script loads .env, builds the Flask app
via the factory, and serves it with waitress (a production WSGI server — the
Flask dev server in run.py must NOT be used in production).
"""
import os
import sys

# ── make the project root importable regardless of how IIS launches us ──
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# ── load .env (SECRET_KEY, DATABASE_URL, etc.) ──────────────────────────
try:
    from dotenv import load_dotenv
    env_path = os.path.join(APP_DIR, '.env')
    load_dotenv(env_path)
    print(f"[serve] Loaded .env from {env_path}", flush=True)
except Exception as exc:
    print(f"[serve] .env not loaded: {exc}", flush=True)

# force production config under IIS
os.environ.setdefault('FLASK_ENV', 'production')

from app import create_app          # noqa: E402
from waitress import serve          # noqa: E402

app = create_app(os.environ.get('FLASK_ENV', 'production'))

if __name__ == '__main__':
    # IIS/HttpPlatformHandler passes the internal port in PORT.
    port = int(os.environ.get('PORT', '5001'))
    print(f"[serve] App dir      : {APP_DIR}", flush=True)
    print(f"[serve] Serving on   : http://127.0.0.1:{port}", flush=True)
    print(f"[serve] FLASK_ENV    : {os.environ.get('FLASK_ENV')}", flush=True)
    print(f"[serve] FREECAD_CMD  : {os.environ.get('FREECAD_CMD', '(default search)')}", flush=True)
    print(f"[serve] DB configured: {'yes' if os.environ.get('DATABASE_URL') else 'config.py default'}", flush=True)
    # threads: allow a few concurrent requests; FreeCAD/cadquery are subprocess/CPU heavy
    serve(app, host='127.0.0.1', port=port, threads=8,
          channel_timeout=300)
