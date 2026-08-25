from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.companies import router as companies_router
from app.api.v1.opportunities import router as opportunities_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.quotes import router as quotes_router
from app.api.v1.screener import router as screener_router
from app.api.v1.theses import router as theses_router
from app.api.v1.watchlist import router as watchlist_router

router = APIRouter()
router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(companies_router)
router.include_router(opportunities_router)
router.include_router(portfolio_router)
router.include_router(quotes_router)
router.include_router(screener_router)
router.include_router(theses_router)
router.include_router(watchlist_router)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
