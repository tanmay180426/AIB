"""Free-only policy, real local HTTP provider protocol and actual scoped API data."""
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from pydantic import ValidationError
from app.core.config import Settings, local_llm_url, settings
from app.ai_assistant.provider import OllamaProvider, provider_status


@pytest.mark.parametrize('url', ['http://localhost:11434', 'http://127.0.0.1:11434/', 'http://[::1]:11434'])
def test_loopback_configuration_is_supported(url):
    assert local_llm_url(url) == url.rstrip('/')


@pytest.mark.parametrize('url', ['https://api.openai.com', 'https://ollama.com', 'http://192.168.1.10:11434',
    'http://localhost.evil.invalid', 'http://secret-user:secret-password@localhost:11434',
    'http://localhost:11434?token=secret', 'file:///tmp/server', 'http://localhost:bad', 'http://[bad'])
def test_remote_or_credentialed_model_urls_fail_without_echoing_secrets(url):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, OLLAMA_BASE_URL=url)
    assert 'loopback URL' in str(error.value)
    assert url not in str(error.value)


@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'gemini', 'openrouter', 'typo'])
def test_unsupported_provider_fails_clearly(provider):
    with pytest.raises(ValidationError, match='supports only ollama'):
        Settings(_env_file=None, LLM_PROVIDER=provider)


def test_default_requires_no_provider_credentials(monkeypatch):
    for key in list(__import__('os').environ):
        if any(name in key.upper() for name in ('OPENAI', 'ANTHROPIC', 'GEMINI', 'OPENROUTER')):
            monkeypatch.delenv(key)
    config = Settings(_env_file=None, ENABLE_LLM_ASSISTANT=False, LLM_PROVIDER='ollama', OLLAMA_BASE_URL='http://localhost:11434')
    assert config.LLM_PROVIDER == 'ollama' and not config.ENABLE_LLM_ASSISTANT
    assert not any('api_key' in field for field in Settings.model_fields)


@contextmanager
def local_protocol_server(redirect=False, remote=False):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            calls.append(('GET', self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"models":[]}')
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(('POST', self.path, body))
            self.send_response(307 if redirect else 200)
            if redirect:
                self.send_header('Location', 'https://paid-provider.invalid/generate')
            self.end_headers()
            if self.path == '/api/show':
                metadata = {'model_info': {'general.architecture': 'fixture'}}
                if remote:
                    metadata['remote_model'] = 'cloud-model'
                    metadata['remote_host'] = 'https://ollama.com'
                self.wfile.write(json.dumps(metadata).encode())
            else:
                self.wfile.write(b'{"response":"Local protocol fixture response"}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_real_local_provider_protocol_ignores_proxy_settings(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://paid-proxy.invalid:9999')
    monkeypatch.setenv('HTTPS_PROXY', 'http://paid-proxy.invalid:9999')
    monkeypatch.setenv('ALL_PROXY', 'http://paid-proxy.invalid:9999')
    monkeypatch.setenv('NO_PROXY', '')
    with local_protocol_server() as (url, calls):
        monkeypatch.setattr(settings, 'ENABLE_LLM_ASSISTANT', True)
        monkeypatch.setattr(settings, 'OLLAMA_BASE_URL', url)
        assert provider_status()['reachable'] is True
        result = OllamaProvider(url, 'protocol-fixture', 2).generate('Safe fixture prompt')
        assert result['status'] == 'available'
        assert calls[0] == ('GET', '/api/tags')
        assert calls[1][0:2] == ('POST', '/api/show')
        assert calls[1][2] == {'model': 'protocol-fixture'}
        assert calls[2][0:2] == ('POST', '/api/generate')
        assert calls[2][2] == {'model': 'protocol-fixture', 'prompt': 'Safe fixture prompt', 'stream': False}


@pytest.mark.parametrize('model', ['gpt-oss:120b-cloud', 'example:cloud'])
def test_cloud_model_tags_fail_configuration(model):
    with pytest.raises(ValidationError, match='installed local model'):
        Settings(_env_file=None, OLLAMA_MODEL=model)


def test_remote_model_alias_never_receives_prompt():
    with local_protocol_server(remote=True) as (url, calls):
        result = OllamaProvider(url, 'innocent-alias', 2).generate('private question')
        assert result['status'] == 'unavailable' and result['error'] == 'LocalModelRequired'
        assert len(calls) == 1 and calls[0][1] == '/api/show'
        assert 'prompt' not in calls[0][2]


def test_local_server_cannot_redirect_to_hosted_provider():
    with local_protocol_server(redirect=True) as (url, calls):
        result = OllamaProvider(url, 'protocol-fixture', 2).generate('Safe fixture prompt')
        assert result['status'] == 'unavailable'
        assert result['error'] == 'HTTPStatusError'
        assert len(calls) == 1


def test_runtime_provider_guard_and_safe_error_details(monkeypatch, caplog):
    import httpx
    def forbidden(*args, **kwargs):
        pytest.fail('A blocked provider must not make any HTTP request.')
    monkeypatch.setattr(httpx, 'post', forbidden)
    monkeypatch.setattr(httpx, 'get', forbidden)
    result = OllamaProvider('https://secret-user:secret-password@remote.invalid', 'unused', 1).generate('private question')
    assert result == {'text': '', 'status': 'unavailable', 'provider': 'ollama', 'error': 'ValueError'}
    monkeypatch.setattr(settings, 'ENABLE_LLM_ASSISTANT', True)
    monkeypatch.setattr(settings, 'OLLAMA_BASE_URL', 'https://remote.invalid')
    assert provider_status()['reachable'] is False
    assert provider_status()['base_url'] is None
    assert 'private question' not in caplog.text and 'secret-password' not in caplog.text


def test_real_scoped_calculations_never_call_provider_and_unavailable_is_truthful(client, analyst_auth, monkeypatch):
    import httpx
    original_get, original_post = httpx.get, httpx.post
    def forbidden(*args, **kwargs):
        pytest.fail('Numerical Insights must not contact the provider.')
    monkeypatch.setattr(settings, 'ENABLE_LLM_ASSISTANT', True)
    monkeypatch.setattr(httpx, 'post', forbidden)
    monkeypatch.setattr(httpx, 'get', forbidden)
    original = client.get('/api/datasets', headers=analyst_auth).json()['active_dataset_id']
    uploaded = []
    try:
        for amount in (200, 800):
            data = f'date,region,revenue\n2025-01-01,Pune,{amount}\n2025-01-02,Delhi,500\n'
            response = client.post('/api/datasets/upload', headers=analyst_auth,
                data={'name': 'Free-only fixture'}, files={'file': ('free.csv', data.encode())})
            assert response.status_code == 201
            identifier = response.json()['dataset_id']
            uploaded.append(identifier)
            assert client.post(f'/api/datasets/{identifier}/select', headers=analyst_auth).status_code == 200
            response = client.post('/api/insights/query', headers=analyst_auth,
                params={'column_filters': '{"region":"Pune"}'}, json={'question': 'What is the total revenue?'})
            body = response.json()
            assert response.status_code == 200 and body['provider'] == 'computed'
            assert body['dataset_id'] == identifier and f'{amount:.2f}' in body['answer']
            assert body['sources'] == [f'dataset:{identifier}:aggregates']
        # A real enabled provider attempts only a loopback socket that has no server.
        with ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as temporary:
            unused_port = temporary.server_port
        monkeypatch.setattr(settings, 'OLLAMA_BASE_URL', f'http://127.0.0.1:{unused_port}')
        monkeypatch.setattr(httpx, 'get', original_get)
        monkeypatch.setattr(httpx, 'post', original_post)
        monkeypatch.setattr(settings, 'ENABLE_LLM_ASSISTANT', True)
        monkeypatch.setattr(settings, 'OLLAMA_BASE_URL', f'http://127.0.0.1:{unused_port}')
        result = client.post('/api/insights/query', headers=analyst_auth, json={'question': 'Tell me a joke'}).json()
        assert result['status'] == 'llm_unavailable'
        assert 'cannot answer that question' in result['answer']
        assert result['provider'] == 'ollama'
    finally:
        for identifier in uploaded:
            client.delete(f'/api/datasets/{identifier}', headers=analyst_auth)
        if original:
            assert client.post(f'/api/datasets/{original}/select', headers=analyst_auth).status_code == 200
