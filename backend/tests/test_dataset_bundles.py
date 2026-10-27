"""Real bundle storage/auth/analytics contracts; all fixtures are synthetic."""
import io
import stat
import zipfile

import pytest
from sqlalchemy import inspect, select

from tests.test_datasets import isolated  # noqa: F401
from app.models.dataset import Dataset, DatasetBundleTable
from app.services import dataset_bundles as bundles, datasets as service

SALES = b'date,order_id,region,revenue\n2025-01-01,a,Pune,200\n2025-01-02,b,Delhi,800\n'
ITEMS = b'order_id,product_id,price\na,x,30\na,y,70\nb,z,90\n'
PAYMENTS = b'order_id,payment_value\na,40\na,60\nb,90\n'


def upload(client, auth, paths=None, contents=None):
    paths = paths or ['folder/orders.csv', 'folder/nested/items.csv', 'folder/payments.csv']
    contents = contents or [SALES, ITEMS, PAYMENTS]
    return client.post('/api/datasets/bundles/upload', headers=auth,
                       data={'name': 'Synthetic bundle', 'paths': paths},
                       files=[('files', (p.split('/')[-1], raw, 'text/csv')) for p, raw in zip(paths, contents)])


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        for path, content in entries:
            z.writestr(path, content)
    return stream.getvalue()


def test_independent_tables_selection_preview_and_no_joins(isolated, analyst_auth):
    client, factory = isolated
    r = upload(client, analyst_auth); assert r.status_code == 201, r.text
    parent = r.json(); tables = {t['relative_path']: t for t in parent['tables']}
    assert len(tables) == 3
    assert parent['row_count'] == 8
    assert parent['relational_analysis']['supported'] is False
    assert 'no joins' in parent['relational_analysis']['reason']
    listing = client.get('/api/datasets', headers=analyst_auth).json()
    assert [d['dataset_id'] for d in listing['datasets']] == [parent['dataset_id']]
    orders = tables['folder/orders.csv']
    assert orders['row_count'] == 2 and orders['column_count'] == 4
    assert orders['schema']['columns'][3]['dtype'] == 'numeric'
    assert orders['semantics']['fields']['revenue'] == 'revenue'
    selected = client.post(f"/api/datasets/{orders['dataset_id']}/select", headers=analyst_auth)
    assert selected.json()['bundle_id'] == parent['dataset_id']
    overview = client.get('/api/analytics/overview', headers=analyst_auth).json()
    assert next(c['value'] for c in overview['metric_cards'] if c['label'] == 'Total revenue') == 1000
    assert next(c['value'] for c in overview['metric_cards'] if c['label'] == 'Orders / transactions') == 2
    filtered = client.get('/api/analytics/overview?column_filters={"region":"Pune"}', headers=analyst_auth).json()
    assert filtered['kpis']['total_revenue'] == 200
    csv = client.get('/api/reports/export?report=dataset_rows&column_filters={"region":"Pune"}', headers=analyst_auth)
    assert csv.status_code == 200 and 'Delhi' not in csv.text
    preview = client.get(f"/api/datasets/{orders['dataset_id']}/preview", headers=analyst_auth).json()
    assert len(preview['rows']) == 2 and preview['rows'][0]['revenue'] == 200
    assert client.get('/api/analytics/overview', headers={**analyst_auth, 'X-Dataset-ID': parent['dataset_id']}).status_code == 409
    with factory() as db:
        assert len(db.scalars(select(DatasetBundleTable)).all()) == 3


def test_duplicate_basenames_bom_and_retry(isolated, analyst_auth):
    client, _ = isolated
    for _ in range(2):
        r = upload(client, analyst_auth, ['folder/a/sales.csv', 'folder/b/sales.csv'], [b'\xef\xbb\xbf'+SALES, ITEMS])
        assert r.status_code == 201, r.text
        assert len({t['internal_name'] for t in r.json()['tables']}) == 2
        assert len({t['dataset_id'] for t in r.json()['tables']}) == 2


@pytest.mark.parametrize('path,raw', [('bad.csv', b''), ('bad.csv', b'a,a\n1,2'), ('bad.csv', b'a,b\n1,2,3'),
    ('bad.csv', b'a,b\n"unfinished,2'), ('bad.txt', SALES), ('../bad.csv', SALES), ('C:/bad.csv', SALES), ('/bad.csv', SALES), ('bad.csv', b'\xff\xff')])
def test_atomic_validation(isolated, analyst_auth, path, raw):
    client, factory = isolated
    r = upload(client, analyst_auth, ['ok.csv', path], [SALES, raw])
    assert r.status_code == 422, r.text
    with factory() as db:
        assert db.scalars(select(Dataset)).all() == []
        assert not any(t.startswith('dataset_') for t in inspect(db.get_bind()).get_table_names())
    assert upload(client, analyst_auth).status_code == 201


def test_conflicting_path_and_empty_collection(isolated, analyst_auth):
    client, _ = isolated
    assert upload(client, analyst_auth, ['a.csv', 'A.csv'], [SALES, ITEMS]).status_code == 422
    assert client.post('/api/datasets/bundles/upload', headers=analyst_auth, data={'name':'Empty'}).status_code == 422


@pytest.mark.parametrize('kind', ['bytes', 'rows', 'columns', 'cells', 'seconds', 'files'])
def test_resource_limits(isolated, analyst_auth, monkeypatch, kind):
    client, _ = isolated
    if kind == 'files': monkeypatch.setattr(bundles, 'MAX_FILES', 2)
    elif kind in {'rows','cells','seconds'}: monkeypatch.setattr(bundles, 'MAX_'+kind.upper(), 1 if kind != 'seconds' else -1)
    else: monkeypatch.setattr(service, 'MAX_'+kind.upper(), 1)
    r = upload(client, analyst_auth)
    assert r.status_code in (413, 422), r.text
    assert client.get('/api/datasets', headers=analyst_auth).json()['datasets'] == []


@pytest.mark.parametrize('entries', [[('../escape.csv', SALES)], [('/abs.csv', SALES)], [('inner.zip', b'zip')], [('a.csv', SALES), ('a.csv', ITEMS)]])
def test_zip_rejections(isolated, analyst_auth, entries):
    client, _ = isolated
    r = client.post('/api/datasets/bundles/zip', headers=analyst_auth, data={'name':'ZIP'}, files={'file':('test.zip', archive(entries))})
    assert r.status_code == 422, r.text
    assert client.get('/api/datasets', headers=analyst_auth).json()['datasets'] == []


def test_zip_valid_noise_corruption_symlink_and_bomb(isolated, analyst_auth):
    client, _ = isolated
    def send(raw): return client.post('/api/datasets/bundles/zip', headers=analyst_auth, data={'name':'ZIP'}, files={'file':('test.zip',raw)})
    assert send(archive([('data/one.csv', SALES), ('data/two.csv', ITEMS), ('__MACOSX/._data', b'noise')])).status_code == 201
    assert send(b'not a zip').status_code == 422
    z = io.BytesIO()
    with zipfile.ZipFile(z, 'w') as stream:
        entry = zipfile.ZipInfo('link.csv'); entry.create_system=3; entry.external_attr=(stat.S_IFLNK | 0o777)<<16
        stream.writestr(entry, '../secret')
    assert send(z.getvalue()).status_code == 422
    assert send(archive([('bomb.csv', b'a\n'+b'0\n'*100000)])).status_code == 413


def test_ownership_schema_preview_export_and_delete(isolated, analyst_auth, auth):
    client, _ = isolated
    parent = upload(client, analyst_auth).json()
    child = parent['tables'][0]['dataset_id']
    for ident in [parent['dataset_id'], child]:
        assert client.get(f'/api/datasets/{ident}', headers=auth).status_code == 403
        assert client.post(f'/api/datasets/{ident}/select', headers=auth).status_code == 403
        assert client.get(f'/api/datasets/{ident}/preview', headers=auth).status_code == 403
        assert client.patch(f'/api/datasets/{ident}/schema', headers=auth, json={'fields':{}}).status_code == 403
        assert client.delete(f'/api/datasets/{ident}', headers=auth).status_code == 403
        assert client.get('/api/analytics/overview', headers={**auth,'X-Dataset-ID':ident}).status_code == 403
        assert client.get('/api/reports/export?report=dataset_rows', headers={**auth,'X-Dataset-ID':ident}).status_code == 403
    assert client.delete(f'/api/datasets/{child}', headers=analyst_auth).status_code == 409
    assert client.post(f"/api/datasets/{parent['dataset_id']}/select", headers=analyst_auth).status_code == 200
    assert client.delete(f"/api/datasets/{parent['dataset_id']}", headers=analyst_auth).status_code == 204
    assert client.get('/api/datasets', headers=analyst_auth).json()['datasets'] == []
    assert client.get('/api/analytics/overview', headers=analyst_auth).status_code == 404


def test_admin_and_anonymous_and_legacy(isolated, auth):
    client, _ = isolated
    assert upload(client, {}).status_code == 401
    assert upload(client, auth).status_code == 201
    r = client.post('/api/datasets/upload',headers=auth,data={'name':'Legacy'},files={'file':('single.csv',SALES)})
    assert r.status_code == 201 and r.json()['status'] == 'READY'


def test_storage_failure_cleanup(isolated, analyst_auth, monkeypatch):
    client, factory = isolated
    original = service.storage_table
    calls = 0
    def fail(ds, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2: raise RuntimeError('synthetic storage failure')
        return original(ds, *args, **kwargs)
    monkeypatch.setattr(service, 'storage_table', fail)
    assert upload(client, analyst_auth).status_code == 422
    with factory() as db:
        assert not db.scalars(select(Dataset)).all()
        assert not any(t.startswith('dataset_') for t in inspect(db.get_bind()).get_table_names())


def test_total_rows_and_bytes_cannot_be_bypassed(isolated, analyst_auth, monkeypatch):
    client, _ = isolated
    monkeypatch.setattr(bundles, 'MAX_ROWS', 4)
    # Each table fits individually, but 2+3 rows exceeds the bundle budget.
    r = upload(client, analyst_auth, ['orders.csv','items.csv'], [SALES,ITEMS])
    assert r.status_code == 422 and '5 rows' in r.json()['detail']
    monkeypatch.setattr(bundles, 'MAX_ROWS', 5000000)
    monkeypatch.setattr(service, 'MAX_BYTES', max(len(SALES),len(ITEMS))+1)
    assert upload(client, analyst_auth, ['orders.csv','items.csv'], [SALES,ITEMS]).status_code == 413
    assert client.get('/api/datasets',headers=analyst_auth).json()['datasets'] == []


def test_zip_preview_and_entry_count_limits(isolated, analyst_auth):
    client, _ = isolated
    def preview(raw):
        return client.post('/api/datasets/bundles/zip-preview',headers=analyst_auth,files={'file':('fixture.zip',raw)})
    r=preview(archive([('one.csv',SALES),('nested/two.csv',ITEMS)]))
    assert r.status_code == 200 and len(r.json()['files']) == 2
    assert r.json()['total_bytes'] == len(SALES)+len(ITEMS)
    assert preview(archive([('.DS_Store',b'noise')])).status_code == 422
    assert preview(archive([(f'{i}.csv',SALES) for i in range(33)])).status_code == 413
    assert preview(archive([(f'{i}/',b'') for i in range(65)])).status_code == 413
    assert client.get('/api/datasets',headers=analyst_auth).json()['datasets'] == []
