"""Real route contracts on disposable storage; all registered HTTP routes accounted for."""
import inspect
import re

import pytest
from fastapi.routing import APIRoute
from app.main import app


def deps(dependant):
    result = []
    for dependency in dependant.dependencies:
        call = dependency.call
        name = getattr(call, '__name__', type(call).__name__)
        roles = inspect.getclosurevars(call).nonlocals.get('roles') if inspect.isfunction(call) else None
        result.append(name + (str(roles) if roles else ''))
        result.extend(deps(dependency))
    return result


def concrete(path):
    return re.sub(r'\{[^}]+\}', 'missing-audit-resource', path)


PROTECTED = [(method, route.path) for route in app.routes if isinstance(route, APIRoute)
             and 'get_current_user' in deps(route.dependant) for method in sorted(route.methods)]
ADMIN = [(method, route.path) for route in app.routes if isinstance(route, APIRoute)
         and any(d in deps(route.dependant) for d in ['require_admin', "checker('admin',)"])
         for method in sorted(route.methods)]


@pytest.mark.parametrize('method,path', PROTECTED)
def test_each_protected_route_rejects_anonymous(client, method, path):
    response = client.request(method, concrete(path))
    assert response.status_code == 401, (method, path, response.text)
    assert isinstance(response.json()['detail'], str)


@pytest.mark.parametrize('method,path', ADMIN)
def test_each_admin_route_rejects_analyst(client, analyst_auth, method, path):
    response = client.request(method, concrete(path), headers=analyst_auth)
    assert response.status_code == 403, (method, path, response.text)


READ_CONTRACTS = {
    '/api/dashboard/kpis': {'filters', 'kpis'},
    '/api/dashboard/monthly-revenue': {'series'},
    '/api/dashboard/revenue-by-category': {'series'},
    '/api/dashboard/orders-by-status': {'series'},
    '/api/analytics/filters': {'date_range'},
    '/api/analytics/overview': {'kpis', 'revenue_series'},
    '/api/analytics/sales': {'kpis'}, '/api/analytics/orders': {'kpis'},
    '/api/analytics/customers': set(), '/api/analytics/products': set(),
    '/api/analytics/sellers': set(), '/api/analytics/delivery': set(),
    '/api/ml/status': {'features', 'dataset_id'},
    '/api/ml/models/sales_forecast_revenue': {'features_schema', 'artifact', 'compatibility'},
    '/api/ml/forecast': {'status', 'compatibility', 'dataset_id'},
    '/api/ml/segments/customers': {'status', 'compatibility', 'dataset_id'},
    '/api/ml/anomalies': {'status', 'compatibility', 'dataset_id'},
    '/api/ml/product-segmentation': {'status', 'compatibility', 'dataset_id'},
    '/api/insights/status': set(), '/api/auth/me': {'user'}, '/api/auth/admin/users': {'users'},
    '/api/users/me': {'user'}, '/api/users': {'users'}, '/api/users/roles/metadata': {'roles'},
    '/api/datasets': {'datasets', 'active_dataset_id'},
    '/api/admin/system/status': {'auth_required', 'app'}, '/api/admin/health': {'backend', 'database'},
    '/api/admin/data/etl/status': {'loaded', 'tables'},
    '/api/admin/warehouse/status': {'dialect', 'complete'},
    '/api/admin/ml/status': {'artifact_count', 'features'},
    '/api/admin/settings': {'roles', 'secrets_exposed'},
}


@pytest.mark.parametrize('path,keys', READ_CONTRACTS.items())
def test_authorized_real_read_contracts(client, auth, path, keys):
    response = client.get(path, headers=auth)
    assert response.status_code == 200, (path, response.text)
    assert isinstance(response.json(), dict)
    assert keys <= response.json().keys()
    from app.services.ml import validate_output
    validate_output(response.json())


@pytest.mark.parametrize('report', ['kpis', 'monthly_revenue', 'revenue_by_category', 'orders_by_status'])
def test_real_report_csv_contract(client, analyst_auth, report):
    response = client.get('/api/reports/export', headers=analyst_auth, params={'report': report})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/csv')
    assert report + '.csv' in response.headers['content-disposition']
    assert response.headers['x-dataset-id']


@pytest.mark.parametrize('path', ['/health', '/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc'])
def test_public_framework_and_health_get(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize('path', ['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc'])
def test_explicit_registered_framework_head(client, path):
    assert client.head(path).status_code == 200


def test_auth_refresh_and_self_service_aliases(client, auth):
    name, password = 'audit-password-user', 'audit-pass-123'
    created = client.post('/api/auth/register', headers=auth, json={
        'username': name, 'password': password, 'role': 'analyst'})
    assert created.status_code == 201
    login = client.post('/api/auth/login', data={'username': name, 'password': password})
    assert login.status_code == 200
    token = login.json()
    refreshed = client.post('/api/auth/refresh', json={'refresh_token': token['refresh_token']})
    assert refreshed.status_code == 200 and refreshed.json()['token_type'] == 'bearer'
    headers = {'Authorization': 'Bearer ' + refreshed.json()['access_token']}
    assert client.patch('/api/users/me', headers=headers, json={
        'current_password': password, 'new_password': 'audit-next-123'}).json() == {'status': 'password_updated'}
    assert client.put('/api/users/me', headers=headers, json={
        'current_password': 'audit-next-123', 'new_password': password}).status_code == 200
    assert client.patch(f'/api/users/{name}/role', headers=auth, json={'role': 'admin'}).json()['user']['role'] == 'admin'
    assert client.patch(f'/api/users/{name}/status', headers=auth, json={'is_active': False}).json()['user']['is_active'] is False
    assert client.get('/api/users/me', headers=headers).status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token': token['refresh_token']}).status_code == 401


@pytest.fixture
def restore_analyst_selection(client, analyst_auth):
    # Selection is persisted intentionally. A deleted selection must not fall back
    # silently, so the test restores its original selection explicitly on teardown.
    original = client.get('/api/datasets', headers=analyst_auth).json()['active_dataset_id']
    yield
    if original:
        assert client.post(f'/api/datasets/{original}/select', headers=analyst_auth).status_code == 200


def test_dataset_pipeline_and_independent_aggregation_contract(client, auth, analyst_auth, restore_analyst_selection):
    csv = b'date,order_id,region,revenue\n2025-01-01,o1,Pune,200\n2025-01-02,o2,Delhi,800\n'
    uploaded = client.post('/api/datasets/upload', headers=analyst_auth,
                           data={'name': 'API connectivity fixture'}, files={'file': ('audit.csv', csv)})
    assert uploaded.status_code == 201
    dataset = uploaded.json()
    assert dataset['status'] == 'READY'
    dataset_id = dataset['dataset_id']
    assert client.get(f'/api/datasets/{dataset_id}', headers=auth).status_code == 403
    assert client.post(f'/api/datasets/{dataset_id}/select', headers=analyst_auth).status_code == 200
    changed = client.patch(f'/api/datasets/{dataset_id}/schema', headers=analyst_auth,
        json={'fields': {'date': 'date', 'revenue': 'revenue', 'order': 'order_id', 'location': 'region'},
              'currency_code': 'BRL', 'domain': 'commerce'})
    assert changed.status_code == 200
    scoped = {**analyst_auth, 'X-Dataset-ID': dataset_id}
    params = {'column_filters': '{"region":"Pune"}'}
    overview = client.get('/api/analytics/overview', headers=scoped, params=params).json()
    assert overview['dataset_id'] == dataset_id
    assert overview['kpis']['total_revenue'] == 200
    answer = client.post('/api/insights/query', headers=scoped, params=params,
                         json={'question': 'What is the total revenue?', 'context_limit': 20})
    assert answer.status_code == 200
    assert '200.00' in answer.json()['answer']
    for report in ('dataset_rows', 'numeric_statistics'):
        exported = client.get('/api/reports/export', headers=scoped, params={**params, 'report': report})
        assert exported.status_code == 200
        assert exported.headers['x-dataset-id'] == dataset_id
        assert 'Delhi' not in exported.text
    incompatible = client.post('/api/ml/predict/sales', headers=scoped, json={
        'purchase_month': 1, 'purchase_weekday': 0, 'purchase_hour': 12, 'n_items': 1})
    assert incompatible.status_code == 200 and incompatible.json()['status'] == 'not_applicable'
    assert client.delete(f'/api/datasets/{dataset_id}', headers=analyst_auth).status_code == 204
    assert client.get('/api/dashboard/kpis', headers=analyst_auth).status_code == 404


def test_cors_allowed_origin_and_unknown_origin(client):
    headers = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
               'Access-Control-Request-Headers': 'Authorization,X-Dataset-ID,Content-Type'}
    allowed = client.options('/api/ml/predict/sales', headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers['access-control-allow-origin'] == 'http://localhost:5173'
    denied = client.options('/api/ml/predict/sales', headers={**headers, 'Origin': 'https://untrusted.invalid'})
    assert denied.status_code == 400


def test_optional_llm_fallback_is_honest_and_dataset_scoped(client, analyst_auth):
    response = client.post('/api/insights/query', headers=analyst_auth,
                           json={'question': 'Tell me a joke', 'context_limit': 20})
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'llm_unavailable'
    assert body['answer']
    assert body['sources'] == [f"dataset:{body['dataset_id']}:aggregates"]


def test_export_openapi_documents_actual_csv_contract(client):
    response = client.get('/openapi.json').json()['paths']['/api/reports/export']['get']['responses']['200']
    assert 'text/csv' in response['content']
    assert 'application/json' not in response['content']
