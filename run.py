import os
from dotenv import load_dotenv


load_dotenv()

from app import create_app

app = create_app(os.environ.get('FLASK_ENV', 'development'))

if __name__ == '__main__':
    # NOTE: Werkzeug's processes=N option forks worker processes via
    # os.fork(), which does not exist on Windows — it can never work here.
    # threaded=True is restored for normal I/O concurrency. The actual
    # fix for CAD-kernel calls blocking other requests (cadquery/OCP
    # holding the GIL during circular-window boolean cuts) is to run
    # that specific work in a child process via `multiprocessing`
    # (spawn-based, works on Windows) — see model3d_assembly.py.
    app.run(debug=True, host='0.0.0.0', port=5001, threaded=True)