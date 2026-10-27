"""Exercise an empty-database first run through a real loopback API server."""
import argparse
import json
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--api-url', default='http://localhost:8033')
args = parser.parse_args()
with httpx.Client(base_url=args.api_url, trust_env=False, timeout=30) as client:
    assert client.get('/health').json() == {'status': 'ok'}
    accounts = {}
    for name in ('admin', 'analyst'):
        response = client.post('/api/auth/login', data={'username': name, 'password': name + '123'})
        assert response.status_code == 200
        accounts[name] = {'Authorization': 'Bearer ' + response.json()['access_token']}
    admin, analyst = accounts['admin'], accounts['analyst']
    assert client.get('/api/admin/health', headers=analyst).status_code == 403
    assert client.get('/api/admin/health').status_code == 401
    users = client.get('/api/users', headers=admin).json()['users']
    assert len(users) == 2
    assert client.get('/api/datasets', headers=analyst).json()['datasets'] == []
    missing = client.get('/api/analytics/overview', headers=analyst)
    assert missing.status_code == 409 and 'Select' in missing.json()['detail']
    identifiers = {}
    fixture = b'date,order_id,region,revenue\n2025-01-01,o1,Pune,200\n2025-01-02,o2,Delhi,800\n'
    for name, headers in accounts.items():
        uploaded = client.post('/api/datasets/upload', headers=headers,
            data={'name': 'Sanitized first-run fixture'}, files={'file': ('fixture.csv', fixture, 'text/csv')})
        assert uploaded.status_code == 201 and uploaded.json()['status'] == 'READY'
        identifier = uploaded.json()['dataset_id']
        identifiers[name] = identifier
        assert client.post(f'/api/datasets/{identifier}/select', headers=headers).status_code == 200
        scoped = {**headers, 'X-Dataset-ID': identifier}
        overview = client.get('/api/analytics/overview', headers=scoped).json()
        assert overview['dataset_id'] == identifier and overview['kpis']['total_revenue'] == 1000
        for section in ('sales', 'orders', 'customers', 'products', 'sellers', 'delivery'):
            response = client.get('/api/analytics/' + section, headers=scoped)
            assert response.status_code == 200
        filtered = {'column_filters': '{"region":"Pune"}'}
        answer = client.post('/api/insights/query', headers=scoped, params=filtered,
            json={'question': 'What is the total revenue?'}).json()
        assert answer['provider'] == 'computed' and '200.00' in answer['answer']
        csv = client.get('/api/reports/export', headers=scoped, params={**filtered, 'report': 'dataset_rows'})
        assert csv.status_code == 200 and 'Pune' in csv.text and 'Delhi' not in csv.text
        status = client.get('/api/ml/status', headers=scoped).json()
        assert all(not model['artifact_available'] for feature in status['features'] for model in feature['models'])
        forecast = client.get('/api/ml/forecast', headers=scoped).json()
        assert forecast['status'] == 'not_applicable' and 'forecast' not in forecast
        limitation = client.post('/api/insights/query', headers=scoped, json={'question': 'Tell me a joke'}).json()
        assert limitation['status'] == 'llm_unavailable' and limitation['provider'] == 'disabled'
    assert client.get(f"/api/datasets/{identifiers['analyst']}", headers=admin).status_code == 403
    for path in ('system/status', 'health', 'data/etl/status', 'warehouse/status', 'ml/status', 'settings'):
        assert client.get('/api/admin/' + path, headers=admin).status_code == 200
    assert len(client.get('/api/users', headers=admin).json()['users']) == 2
    print(json.dumps({'first_run_bootstrap': 'existing login/user service', 'seed_users': 2,
        'initial_datasets': 0, 'uploaded_dataset_revenue': 1000, 'filtered_revenue': 200,
        'roles_and_ownership': 'passed', 'optional_models': 'absent, honest Not Applicable',
        'optional_ollama': 'disabled, honest fallback', 'admin_reads': 'passed',
        'fixture_dataset_ids': identifiers}))
