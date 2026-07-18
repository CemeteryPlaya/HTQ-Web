"""Orchestrator — send_email use case."""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.domain import EmailMessage, EmailRecipientStatus
from app.services.dlp_scanner import OutboundDLPScanner

async def send_email(
    session: AsyncSession,
    *, sender_id: int, subject: str, body: str,
    recipients: list[int], external_recipients: list[str] = None,
    attachments: list[dict] = None,
) -> EmailMessage:
    # 1. DLP
    OutboundDLPScanner().check_and_raise(subject, body)

    # 2. atomic create EmailMessage + RecipientStatus + Attachments
    message = EmailMessage(
        sender_id=sender_id, 
        subject=subject, 
        body=body,
        is_draft=False, 
        sent_at=datetime.utcnow(),
        external_recipients=external_recipients or []
    )
    session.add(message)
    await session.flush()
    
    for uid in recipients:
        session.add(EmailRecipientStatus(
            message_id=message.id, 
            user_id=uid,
            recipient_type="to", 
            folder="inbox"
        ))
        
    # 3. enqueue Dramatiq deliver_email
    from app.workers.actors import deliver_email
    deliver_email.send(message.id)
    
    await session.commit()
    return message
