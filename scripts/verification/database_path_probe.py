"""Read configuration from several launch directories without creating a database."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
env = dict(os.environ)
env['PYTHONPATH'] = str(ROOT / 'backend')
env['DATABASE_URL'] = 'sqlite:///./sem5.db'
command = [sys.executable, '-c', 'from app.core.config import settings; print(settings.DATABASE_URL)']
paths = {str(folder.relative_to(ROOT)) or '.': subprocess.check_output(command, cwd=folder, env=env, text=True).strip()
         for folder in (ROOT, ROOT / 'backend', ROOT / 'frontend')}
assert len(set(paths.values())) == 1
assert next(iter(paths.values())) == 'sqlite:///' + (ROOT / 'backend/sem5.db').as_posix()
print(json.dumps({'stable_default_database_by_launch_directory': paths}))
