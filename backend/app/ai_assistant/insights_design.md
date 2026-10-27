# insights_design.md
- LLM: Ollama preferred (local). Provider-agnostic interface in backend/app/ai_assistant/provider.py
- Tools: controlled functions (only authorized data via backend APIs/services), no arbitrary SQL
- Context: RBAC-aware, filter by role/permissions
- Fallback: if LLM unavailable -> return llm_unavailable with honest message
- Safety: validate prompts, cap context size, no secrets
