from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Asset


def search_assets(db: Session, query: str, limit: int = 20) -> list[Asset]:
    pattern = f"%{query}%"
    return (
        db.query(Asset)
        .filter(Asset.active.is_(True))
        .filter(or_(Asset.symbol.ilike(pattern), Asset.name.ilike(pattern)))
        .order_by(Asset.symbol)
        .limit(limit)
        .all()
    )
