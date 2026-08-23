from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.companies import router as companies_router

router = APIRouter()
router.include_router(admin_router)
router.include_router(companies_router)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
