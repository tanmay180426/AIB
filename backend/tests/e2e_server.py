"""Run the real API on a disposable copy of the reference warehouse for E2E.

Browser uploads and role changes must never modify the developer's database.
SQLite backup provides a consistent copy even when the source uses WAL.
"""
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    # Explicit reference fixtures let a sanitized workspace run regressions
    # without copying a developer database into the source snapshot.
    source = Path(os.environ.get('SEM5_E2E_REFERENCE_DB') or (Path(__file__).resolve().parents[1] / "sem5.db"))
    with tempfile.TemporaryDirectory(prefix="sem5-e2e-") as directory:
        database = Path(directory) / "warehouse.db"
        if source.exists():
            with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as original, closing(sqlite3.connect(database)) as copy:
                original.backup(copy)
                # Per-user selection is reset for a deterministic test start.
                if copy.execute("SELECT 1 FROM sqlite_master WHERE name='app_dataset_selection'").fetchone():
                    copy.execute("DELETE FROM app_dataset_selection")
                    copy.commit()
        os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
        os.environ["ENABLE_LLM_ASSISTANT"] = "false"
        import uvicorn
        from app.main import app
        from fastapi.middleware.cors import CORSMiddleware
        origin = os.environ.get('SEM5_E2E_FRONTEND_URL', 'http://localhost:5173')
        for middleware in app.user_middleware:
            if middleware.cls is CORSMiddleware:
                middleware.kwargs['allow_origins'] = [origin]
        try:
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get('SEM5_E2E_BACKEND_PORT', '8000')))
        finally:
            from app.database.session import engine
            engine.dispose()
