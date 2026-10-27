"""Copy version-controlled/current source into a new sanitized temporary workspace."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
destination = Path(tempfile.gettempdir()) / ('sem5-sanitized-current-tree-' + uuid4().hex)
if destination.exists():
    raise RuntimeError('Snapshot destination already exists; nothing was overwritten.')
paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
excluded_parts = {'.git', 'node_modules', '.venv', '__pycache__', '.pytest_cache', '.universal_work', 'uploads', 'test-results', 'playwright-report'}
excluded_suffixes = {'.db', '.sqlite', '.sqlite3', '.joblib', '.pkl', '.h5', '.onnx', '.gguf', '.pyc', '.log', '.zip'}
included, excluded = [], []
for relative in sorted(set(paths) - {''}):
    source = ROOT / relative
    if (not source.is_file() or source.is_symlink() or excluded_parts.intersection(source.parts)
            or source.suffix.lower() in excluded_suffixes
            or (source.name.startswith('.env') and source.name != '.env.example')):
        excluded.append(relative)
        continue
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    included.append(relative)
manifest = {'kind': 'sanitized uncommitted working-tree snapshot; not a Git clone',
            'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'included_files': included, 'excluded_files': excluded}
(destination / 'SANITIZED_SNAPSHOT_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps({'snapshot_path': str(destination), 'included': len(included), 'excluded': excluded}))
