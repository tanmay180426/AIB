from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai_assistant import context as ctx
from app.ai_assistant.provider import ProviderFactory, provider_status
from app.api.deps import get_current_user
from app.database.deps import get_db
from app.analytics.filters import Filters, analytics_filters

router = APIRouter()


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    context_limit: int = Field(20, ge=1, le=50)


@router.get("/status")
def insights_status():
    return provider_status()


@router.post("/query")
def insights_query(
    payload: QueryRequest,
    f: Filters = Depends(analytics_filters),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # Business BI feature: both roles get the full warehouse context.
    # Administrative data is never exposed to the assistant.
    role = user.get("role", "analyst")

    context = ctx.build_context(db, role, f)
    sources = [f"dataset:{context['dataset_id']}:aggregates"]

    grounded = ctx.grouped_answer(payload.question, db, f) or ctx.numerical_answer(payload.question, context)
    if grounded:
        return {"answer": grounded, "sources": sources, "status": "available", "provider": "computed",
                "role": role, "dataset_id": context["dataset_id"]}

    provider = ProviderFactory.get_provider()
    prompt = ctx.build_prompt(payload.question, context)
    result = provider.generate(prompt, context)

    if result.get("status") == "available":
        answer, status = result["text"], "available"
    else:
        answer, status = ctx.summarize(context), "llm_unavailable"

    return {
        "answer": answer,
        "sources": sources,
        "status": status,
        "provider": result.get("provider"),
        "role": role,
        "dataset_id": context["dataset_id"],
    }
