"""Provider-agnostic LLM interface with a graceful fallback.

Ollama is the preferred provider. If the assistant is disabled or the provider
is unreachable, `generate` returns a structured `unavailable` result so the API
can fall back to a deterministic, data-grounded summary instead of failing.
"""

from __future__ import annotations

from app.core.config import local_llm_model, local_llm_url, settings


class LLMProvider:
    name = "base"

    def generate(self, prompt: str, context: dict | None = None) -> dict:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, context: dict | None = None) -> dict:
        try:
            base_url = local_llm_url(self.base_url)
            model = local_llm_model(self.model)
            import httpx

            # A loopback Ollama daemon can proxy cloud models. Check metadata
            # before sending any prompt or dataset context, including aliases.
            metadata = httpx.post(f"{base_url}/api/show", json={"model": model},
                                  timeout=self.timeout, trust_env=False, follow_redirects=False)
            metadata.raise_for_status()
            details = metadata.json()
            if details.get("remote_host") or details.get("remote_model") or not details.get("model_info"):
                return {"text": "", "status": "unavailable", "provider": self.name,
                        "error": "LocalModelRequired"}
            r = httpx.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=self.timeout,
                trust_env=False,
                follow_redirects=False,
            )
            r.raise_for_status()
            text = (r.json().get("response") or "").strip()
            if not text:
                return {"text": "", "status": "unavailable", "provider": self.name}
            return {"text": text, "status": "available", "provider": self.name, "model": self.model}
        except Exception as exc:  # network, timeout, bad response
            return {
                "text": "",
                "status": "unavailable",
                "provider": self.name,
                "error": type(exc).__name__,
            }


class DisabledProvider(LLMProvider):
    name = "disabled"

    def generate(self, prompt: str, context: dict | None = None) -> dict:
        return {"text": "", "status": "disabled", "provider": self.name}


class ProviderFactory:
    @staticmethod
    def get_provider() -> LLMProvider:
        if not settings.ENABLE_LLM_ASSISTANT:
            return DisabledProvider()
        if settings.LLM_PROVIDER == "ollama":
            return OllamaProvider(
                settings.OLLAMA_BASE_URL, settings.OLLAMA_MODEL, settings.LLM_TIMEOUT_SECONDS
            )
        return DisabledProvider()


def provider_status() -> dict:
    """Report the configured assistant provider and whether it is reachable.

    Used by `GET /api/insights/status`. Never raises — a failed probe is
    reported as `reachable: false` so the UI can explain the fallback.
    """
    if not settings.ENABLE_LLM_ASSISTANT:
        return {
            "enabled": False,
            "provider": "disabled",
            "model": None,
            "reachable": False,
            "fallback": "deterministic data-grounded summary",
        }

    if settings.LLM_PROVIDER != "ollama":
        return {
            "enabled": True,
            "provider": settings.LLM_PROVIDER,
            "model": None,
            "reachable": False,
            "fallback": "deterministic data-grounded summary",
        }

    reachable = False
    try:
        base_url = local_llm_url(settings.OLLAMA_BASE_URL)
        import httpx

        r = httpx.get(f"{base_url}/api/tags", timeout=3, trust_env=False, follow_redirects=False)
        reachable = r.status_code == 200
    except Exception:
        reachable = False

    return {
        "enabled": True,
        "provider": "ollama",
        "model": settings.OLLAMA_MODEL,
        "base_url": base_url if 'base_url' in locals() else None,
        "reachable": reachable,
        "fallback": "deterministic data-grounded summary",
    }
