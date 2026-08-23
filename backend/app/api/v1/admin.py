from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_admin_token
from app.providers.auth.upstox_token_manager import exchange_code_for_token, token_manager
from app.providers.errors import ProviderError

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


class UpstoxTokenRequest(BaseModel):
    code: str


@router.post("/upstox/token")
def refresh_upstox_token(payload: UpstoxTokenRequest) -> dict[str, str]:
    """Redeem a one-time Upstox authorization code (obtained by the human
    owner completing Upstox's own login page) for a fresh access token."""
    try:
        access_token = exchange_code_for_token(payload.code)
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    token_manager.set_token(access_token)
    return {"status": "ok"}
