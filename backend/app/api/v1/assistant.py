"""NL Research Assistant endpoint (Build_plan.md §S step 25, Screener.md
§18). Bare JSON, not the {data, meta} envelope companies.py/opportunities.py
use — this is a generated answer to this user's own question, not
provenance-tagged market data (same reasoning as theses.py/portfolio.py).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.core.security import get_current_verified_user
from app.db.models import AppUser
from app.db.session import get_db
from app.providers.errors import ProviderError
from app.services.research_assistant import ask

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Set by the "ask about this company" follow-up next to the AI summary
    # panel — not validated against a real asset here (an unknown/stale
    # symbol just means the model's get_company_overview call reports it
    # unknown, same as any other tool miss; nothing about this field is
    # trusted beyond plain text folded into the question).
    symbol: str | None = Field(default=None, max_length=32)


@router.post("/ask", dependencies=[rate_limited("nl_assistant")])
def ask_assistant(
    payload: AskRequest,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    if not settings.gemini_api_keys:
        raise HTTPException(status_code=502, detail="GEMINI_API_KEY_1 not configured")

    try:
        answer = ask(
            db,
            current_user,
            payload.question,
            api_keys=settings.gemini_api_keys,
            context_symbol=payload.symbol,
        )
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {"answer": answer.text, "tools_used": answer.tools_used}
