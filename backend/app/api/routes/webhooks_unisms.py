from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth_sms import UniSmsDlrAck, UniSmsDlrPayload
from app.services.unisms_webhook_service import handle_unisms_dlr

router = APIRouter(prefix="/webhooks/unisms", tags=["webhooks"])


@router.post("/dlr", response_model=UniSmsDlrAck)
async def receive_unisms_dlr(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_payload = await request.json()
    payload = UniSmsDlrPayload(**raw_payload)
    handle_unisms_dlr(
        db,
        payload=raw_payload,
        authorization=request.headers.get("Authorization"),
        headers=dict(request.headers),
    )
    return UniSmsDlrAck(ok=True)
