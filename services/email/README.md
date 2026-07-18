# email-service

FastAPI microservice that owns everything about user-facing mail:
provisioning corporate Mailcow mailboxes, exchanging OAuth tokens with
Google and Microsoft, syncing inbox/sent across providers, sending
outbound mail, and serving the React inbox page.

Schema: `email`. Port: `8010` (in compose; published `8010:8010`).

## Account model — the pivot

A single ``email.email_accounts`` row represents a mailbox the user has
linked to the platform — corporate (Mailcow) or personal (Gmail /
Outlook). The frontend sees one flat list and switches between them like
tabs. Provider-specific details live in the existing
``email.provisioned_mailboxes`` (Mailcow) and ``email.oauth_tokens``
(OAuth) tables, with 1:1 FKs from ``email_accounts``.

```
email_accounts (id, user_id, type, provider, address, is_default, is_active,
                mailbox_id  →  provisioned_mailboxes,
                oauth_token_id → oauth_tokens,
                sync_state JSONB,
                last_sync_at, last_sync_error, watch_expires_at)
```

`type='corporate' ↔ mailbox_id IS NOT NULL`,
`type='personal' ↔ oauth_token_id IS NOT NULL` (CHECK enforced).

## OAuth — PKCE flow

* ``POST /api/email/v1/oauth/connect/{provider}`` — backend mints a PKCE
  pair + state nonce, stashes ``{user_id, provider, code_verifier}`` in
  Redis (TTL = ``OAUTH_STATE_TTL_SEC``, default 10 min) and returns
  ``{auth_url, state}``.
* The frontend redirects the browser to ``auth_url``. After consent the
  provider sends the user back to ``GOOGLE_OAUTH_REDIRECT_URI`` (a
  frontend page).
* The callback page calls ``GET /api/email/v1/oauth/callback?code=&state=``.
  The backend looks up state (single-use), exchanges the code, encrypts
  the tokens via ``services/crypto.py`` (AES-256-GCM), upserts
  ``oauth_tokens`` + ``email_accounts (type='personal')``, enqueues
  ``start_account_sync`` + ``register_account_push`` and returns
  ``{status, account_id, address, provider}``.

## Sync drivers — `app/services/sync/`

| Driver | Initial backfill | Incremental | Push |
|---|---|---|---|
| `gmail.py`       | `users.messages.list?labelIds=INBOX,SENT&maxResults=N` → fan-out `messages.get` | `users.history.list?startHistoryId=...`; on 404 → re-baseline | `users.watch` with `topicName=GOOGLE_PUBSUB_TOPIC` |
| `microsoft.py`   | `/me/mailFolders/{folder}/messages?$top=N` per folder + initial `/messages/delta` snapshot | `/me/messages/delta` from saved `@odata.deltaLink` | `POST /me/subscriptions` (Inbox resource, expirationDateTime ≤ 4230 min) |
| `mailcow_imap.py`| One-shot IMAP login → SEARCH ALL → fetch last N per mailbox | One-shot re-poll (Phase 6 IDLE supervisor handles real push) | IMAP IDLE (separate `email-imap-idle` container) |

All drivers UPSERT into ``email_messages`` with
``ON CONFLICT (account_id, message_id) DO UPDATE`` so re-runs are
idempotent. Per-account sync is serialised by
``pg_try_advisory_lock(0x454D4149, account_id)``.

## Push receivers — `app/api/v1/webhooks.py`

Public endpoints (no JWT). Validation happens at the app layer:

* `POST /webhooks/gmail` — Pub/Sub envelope. Verify Bearer JWT via
  google-auth or fall back to `?token=` matched against
  `GOOGLE_PUBSUB_VERIFICATION_TOKEN`.
* `POST /webhooks/microsoft` — initial `?validationToken=` is echoed as
  text/plain; per-notification `clientState` must equal
  `MICROSOFT_WEBHOOK_CLIENT_STATE`; subscription_id → account lookup via
  `sync_state['subscription_id']`.
* `POST /webhooks/mailcow` (optional) — shared header `X-Mailcow-Secret`.

Nginx routes `/api/email/v1/webhooks/` to the service **without**
rate-limiting (rate-limited push deliveries silently drop).

## Send pipeline — `app/services/sender/`

* `gmail.py` — `users.messages.send` with base64url MIME, optional `threadId`.
* `graph.py` — `/me/sendMail` (JSON), `saveToSentItems=true`.
* `mailcow_smtp.py` — `aiosmtplib` on 587 STARTTLS with the per-mailbox
  app-password from `provisioned_mailboxes.encrypted_smtp_app_password`.

`POST /api/email/v1/send` validates the chosen `account_id`, runs DLP,
inserts a row with `folder='outbox'` + per-recipient `RecipientStatus`
rows, then enqueues ``deliver_email`` actor. The actor dispatches to the
right Sender, on success flips `folder='sent'` + records the provider
message/thread IDs + enqueues an incremental sync to reconcile the
provider's Sent folder.

## Cascade delete — user → mailbox

User-service exposes ``DELETE /api/users/v1/admin/users/{id}/`` (admin
only). It:

1. Calls email-service S2S (`POST /mailboxes/{id}/archive/`) so the
   mailbox flips to `status='archived'` (Mailcow `active=0`).
2. Marks the user `status=SUSPENDED` (UserStatus has no `DELETED` enum
   value — soft-delete on this column is enough).
3. Publishes `user.deactivated` and `user.deleted` Redis events.

email-service's ``run_user_events_loop`` (spawned from the FastAPI
lifespan) listens to those channels and:

* On `user.deactivated` — ``EmailAccount.is_active=False`` for personal
  accounts; archives any active corporate mailbox.
* On `user.deleted` — same plus stamps `archived_at = now()` so the
  scheduler picks up the row in the 30-day purge window.

The scheduler's ``final_purge_archived_mailboxes`` (cron daily 03:15)
hard-deletes mailboxes whose `archived_at < now() - MAILBOX_PURGE_AFTER_DAYS`.
Set the env to 0 to test the cascade end-to-end.

`EmailMessage` rows survive mailbox deletion by default (FK is
`ON DELETE SET NULL`). Set
``EMAIL_MESSAGE_PURGE_ON_ACCOUNT_DELETE=true`` to purge them too.

## Containers

| Container | Command | Purpose |
|---|---|---|
| `email-service` | `uvicorn app.main:app --port 8010` | HTTP API + sqladmin + lifespan-spawned `user_events` subscriber |
| `email-worker` | `dramatiq app.workers.actors` | Background actors: sync (`start_account_sync`, `incremental_sync_account`, …), provisioning, `deliver_email` |
| `email-scheduler` | `python -m app.workers.scheduler` | APScheduler jobs: `imap_poll_fallback` (60s), `oauth_token_refresh` (5m), `renew_push_subscriptions` (30m), `final_purge_archived_mailboxes` (cron 03:15), `audit_log_compaction` (cron 03:30) |
| `email-imap-idle` | `python -m app.workers.imap_idle_supervisor` | Long-running per-account IMAP IDLE supervisor (corporate Mailcow). Reacts to `email.account.changed` Redis pub/sub for live add/drop. |

## Storage — bucket `htqweb-mail-attachments`

Phase 4 sync stores attachment metadata only (filename / mime / size).
Phase 7 send pipeline does not yet upload user-attached files. When the
upload UI lands, ``app/services/s3_storage.py`` is the place to wire it
in (it's a per-service copy of the platform storage helper, by the rule
"no shared library").

## Env reference

OAuth + push:
```
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI
GOOGLE_PUBSUB_TOPIC
GOOGLE_PUBSUB_VERIFICATION_TOKEN
MICROSOFT_CLIENT_ID
MICROSOFT_CLIENT_SECRET
MICROSOFT_OAUTH_REDIRECT_URI
MICROSOFT_OAUTH_TENANT_ID    (default "common")
MICROSOFT_WEBHOOK_CLIENT_STATE
WEBHOOK_BASE_URL             (public https URL for the webhooks)
OAUTH_STATE_TTL_SEC          (default 600)
```

Mailcow:
```
MAILCOW_API_URL              (https://mail.example.com/api/v1)
MAILCOW_API_KEY
MAILCOW_DOMAIN
MAILCOW_DEFAULT_QUOTA_MB     (default 1024)
```

Sync + retention:
```
SYNC_INITIAL_BACKFILL_COUNT  (default 200)
ATTACHMENT_MAX_BYTES         (default 26214400 = 25 MB)
PUSH_SUBSCRIPTION_TTL_MINUTES (default 4200, ~3 days)
MAILBOX_PURGE_AFTER_DAYS     (default 30)
EMAIL_MESSAGE_PURGE_ON_ACCOUNT_DELETE  (default false)
```

Crypto + S2S:
```
ENCRYPTION_KEY               (64 hex chars = 32 bytes for AES-256-GCM)
SERVICE_JWT_SECRET           (must match user-service)
```

S3 (defaults to MinIO in dev):
```
STORAGE_BACKEND             (local | s3)
S3_BUCKET=htqweb-mail-attachments
S3_ENDPOINT
S3_ACCESS_KEY
S3_SECRET_KEY
S3_REGION                   (default us-east-1)
```
