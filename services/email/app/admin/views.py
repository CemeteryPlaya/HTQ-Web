"""Admin views for Email Service."""

from sqladmin import ModelView

from app.models.email import EmailMessage, OAuthToken, RecipientStatus


class OAuthTokenAdmin(ModelView, model=OAuthToken):
    column_list = [OAuthToken.id, OAuthToken.user_id, OAuthToken.provider, OAuthToken.provider_account_id, OAuthToken.is_active]
    name = "OAuth Token"


class EmailMessageAdmin(ModelView, model=EmailMessage):
    column_list = [EmailMessage.id, EmailMessage.user_id, EmailMessage.subject, EmailMessage.folder, EmailMessage.date]
    name = "Email Message"


class RecipientStatusAdmin(ModelView, model=RecipientStatus):
    column_list = [RecipientStatus.id, RecipientStatus.message_id, RecipientStatus.recipient_email, RecipientStatus.status]
    name = "Recipient Status"
