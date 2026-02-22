"""
Хранение и расшифровка API-ключей облачных провайдеров в БД.

Ключи задаются только через веб-админку (PATCH /api/v1/models/providers/:id),
шифруются Fernet перед записью. .env для ключей провайдеров не используется.
"""

import hashlib
import logging
from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings
from src.db.postgres_client import postgres_client

logger = logging.getLogger(__name__)

def _fernet_key() -> bytes:
    """Ключ Fernet из секрета (хранится в env только для шифрования, не ключи провайдеров)."""
    secret = (settings.provider_keys_encryption_secret or settings.jwt_secret_key or "change-me").encode("utf-8")
    return urlsafe_b64encode(hashlib.sha256(secret).digest())


def encrypt_api_key(plain: str) -> str:
    """Шифрует API-ключ для сохранения в БД."""
    if not plain or not plain.strip():
        return ""
    f = Fernet(_fernet_key())
    return f.encrypt(plain.strip().encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted: str | None) -> str | None:
    """Расшифровывает API-ключ из БД. Возвращает None при ошибке или пустом значении."""
    if not encrypted or not encrypted.strip():
        return None
    try:
        f = Fernet(_fernet_key())
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception) as e:
        logger.warning("[provider_keys] Не удалось расшифровать ключ: %s", e)
        return None


async def get_provider_api_key(provider_id: str) -> str | None:
    """Возвращает расшифрованный API-ключ провайдера из БД (только для облачных)."""
    rows = await postgres_client.execute_query(
        "SELECT encrypted_api_key FROM model_providers WHERE id = CAST(:pid AS uuid)",
        {"pid": provider_id},
    )
    if not rows:
        return None
    raw = rows[0].get("encrypted_api_key")
    return decrypt_api_key(raw if isinstance(raw, str) else None)


async def set_provider_api_key(provider_id: str, plain_key: str | None) -> bool:
    """
    Сохраняет или очищает API-ключ провайдера.
    plain_key is None или пустая строка — очистить. Иначе — зашифровать и сохранить.
    Returns True если запись обновлена.
    """
    if plain_key is not None and plain_key.strip():
        encrypted = encrypt_api_key(plain_key)
        await postgres_client.execute_query(
            """
            UPDATE model_providers
            SET encrypted_api_key = :enc, api_key_set = TRUE
            WHERE id = CAST(:pid AS uuid)
            """,
            {"pid": provider_id, "enc": encrypted},
        )
    else:
        await postgres_client.execute_query(
            """
            UPDATE model_providers
            SET encrypted_api_key = NULL, api_key_set = FALSE
            WHERE id = CAST(:pid AS uuid)
            """,
            {"pid": provider_id},
        )
    return True
