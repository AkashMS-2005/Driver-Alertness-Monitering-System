"""Twilio SMS webhook routes — incoming highway assistance replies and delivery reports."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.services.sms_service import sms_service

logger = logging.getLogger("smartdrive")

router = APIRouter()


def _validate_twilio_request(request: Request, form_data: dict):
    """Validate Twilio signature if configured."""
    if not settings.TWILIO_WEBHOOK_VALIDATE_SIGNATURE or not settings.TWILIO_AUTH_TOKEN:
        return

    from twilio.request_validator import RequestValidator

    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    signature = request.headers.get("X-Twilio-Signature", "")

    # Reconstruct public URL if behind reverse proxy/ngrok
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    url = f"{proto}://{host}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    if not validator.validate(url, form_data, signature):
        logger.warning(f"[Twilio Webhook] Invalid signature for URL {url}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio request signature",
        )


@router.post("/sms", response_class=Response)
async def incoming_sms_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Webhook invoked by Twilio when toll/highway assistance responds via SMS.

    Accepts replies such as:
      ACCEPT C99A3DCE
      REJECT C99A3DCE
      ACCEPT
      REJECT
    """
    form_data = dict(await request.form())
    _validate_twilio_request(request, form_data)

    logger.info(f"[Twilio Webhook] Incoming SMS from={From}: {Body}")

    success, reply_msg, emergency_id = await sms_service.handle_incoming_sms(
        from_number=From,
        body=Body,
        message_sid=MessageSid,
        db=db,
    )

    # Return valid TwiML
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"    <Message>{reply_msg}</Message>\n"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def delivery_status_webhook(
    request: Request,
    MessageSid: str = Form(...),
    MessageStatus: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Webhook invoked by Twilio for SMS delivery status callbacks."""
    form_data = dict(await request.form())
    _validate_twilio_request(request, form_data)

    logger.info(f"[Twilio Webhook] Delivery status for SID={MessageSid}: {MessageStatus}")

    await sms_service.handle_delivery_status(
        message_sid=MessageSid,
        message_status=MessageStatus,
        db=db,
    )
    return {"status": "ok", "message_sid": MessageSid, "delivery_status": MessageStatus}
