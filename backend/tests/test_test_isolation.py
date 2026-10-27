from pathlib import Path
import sqlite3
from contextlib import closing

from tests.database_fixture import test_storage as disposable_storage


def test_suite_storage_is_not_application_database(request):
    from app.database.session import engine
    actual = Path(engine.url.database).resolve()
    assert actual == request.config._sem5_test_database.resolve()
    assert actual != (Path(__file__).parents[1] / 'sem5.db').resolve()
    assert actual.parent.name.startswith('sem5-pytest-')


def test_disposable_users_and_role_changes_do_not_touch_original(tmp_path):
    original = tmp_path / 'application.db'
    with closing(sqlite3.connect(original)) as db:
        db.execute('CREATE TABLE app_user (username TEXT, role TEXT)')
        db.execute("INSERT INTO app_user VALUES ('admin', 'admin')")
        db.commit()
    before = original.read_bytes()
    with disposable_storage(original) as isolated:
        with closing(sqlite3.connect(isolated)) as db:
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='app_user'").fetchone()
            db.execute('CREATE TABLE app_user (username TEXT, role TEXT)')
            db.execute("INSERT INTO app_user VALUES ('created-test-user', 'analyst')")
            db.execute("UPDATE app_user SET role='admin'")
            db.commit()
        assert original.read_bytes() == before
    assert not isolated.exists()
    with closing(sqlite3.connect(original)) as db:
        assert db.execute('SELECT username, role FROM app_user').fetchall() == [('admin', 'admin')]
