"""E2EE-ключи пользователя — порт ``services/messenger/app/api/v1/keys.py``
(attachments/keys под-задача, PLAN.md §6.5).

Странность (задокументирована, воспроизведена КАК ЕСТЬ, НЕ исправляется):
фронт (``frontend/src/features/messenger/api/messengerApi.ts::
uploadKeyBundle``) шлёт тело ``{identity_pub_key, signed_prekey,
prekey_signature}`` — это НЕ совпадает с контрактом исходного
``UserKeyCreate`` (``device_id``/``public_identity_key``/``signed_pre_key``/
``signature``): не хватает ``device_id`` вовсе, а остальные три поля названы
иначе. Раз в исходной FastAPI-схеме это Pydantic ``BaseModel`` с обязательными
полями — реальный фронтовый вызов уже ловил бы 422 validation error и в
исходном сервисе (нет ``device_id``, лишние необъявленные поля игнорируются
Pydantic v2, но обязательные ``device_id``/``public_identity_key``/
``signed_pre_key``/``signature`` отсутствуют). Порт воспроизводит СХЕМУ
источника байт-в-байт, а не фронтовый вызов, который был бы одинаково
сломан на обеих сторонах.
"""
from __future__ import annotations

from apps.messenger.models import UserKey


def upsert_key(
    user_id: int, *, device_id: str, public_identity_key: str,
    signed_pre_key: str, signature: str,
) -> UserKey:
    """Порт ``keys.py::upload_keys``: обновляет существующую пару
    (``user_id``, ``device_id``) или создаёт новую."""
    key = UserKey.objects.filter(user_id=user_id, device_id=device_id).first()
    if key is not None:
        key.public_identity_key = public_identity_key
        key.signed_pre_key = signed_pre_key
        key.signature = signature
        key.save(update_fields=["public_identity_key", "signed_pre_key", "signature", "updated_at"])
    else:
        key = UserKey.objects.create(
            user_id=user_id, device_id=device_id, public_identity_key=public_identity_key,
            signed_pre_key=signed_pre_key, signature=signature,
        )
    return key


def get_user_keys(user_id: int) -> list[UserKey]:
    """Порт ``keys.py::get_user_keys``: все устройства пользователя."""
    return list(UserKey.objects.filter(user_id=user_id).order_by("device_id"))


def serialize_key(key: UserKey) -> dict:
    """Порт ``UserKeyRead`` — форма ответа (общая для POST/GET)."""
    return {
        "user_id": key.user_id,
        "device_id": key.device_id,
        "public_identity_key": key.public_identity_key,
        "signed_pre_key": key.signed_pre_key,
        "signature": key.signature,
    }
