from __future__ import annotations

import re
from typing import Any, Optional

USER_SECRET_PREFIX = "user_secret:"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class UserSecretStore:
    """Per-user encrypted secrets.

    Every secret is stored under a private ``user_secret:u<id>:<name>`` name
    *and* carries ``owner_id`` in the database, so a user can only list, read,
    replace or delete their own entries. Values are never returned by the API
    layer; only ``reveal`` (server-side use) decrypts them.
    """

    def __init__(self, database, security) -> None:
        self.db = database
        self.security = security

    @staticmethod
    def validate_name(name: str) -> str:
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValueError("اسم السر غير صالح.")
        return name

    @staticmethod
    def _storage_name(name: str, owner_id: int) -> str:
        return f"{USER_SECRET_PREFIX}u{int(owner_id)}:{name}"

    def _owned(self, name: str, owner_id: int) -> Optional[dict[str, Any]]:
        record = self.db.get_secret_by_name(self._storage_name(name, owner_id))
        if record is None or record.get("owner_id") != int(owner_id):
            return None
        return record

    def set(self, owner_id: int, name: str, value: str, description: str = "") -> dict[str, Any]:
        self.validate_name(name)
        if not isinstance(value, str) or not value:
            raise ValueError("قيمة السر مطلوبة.")
        encrypted = self.security.encrypt(value)
        existing = self._owned(name, owner_id)
        if existing:
            record = self.db.update_secret(
                existing["id"], encrypted_value=encrypted, description=description
            )
        else:
            record = self.db.create_secret(
                name=self._storage_name(name, owner_id),
                encrypted_value=encrypted,
                description=description,
                owner_id=int(owner_id),
            )
        return self._public(name, record or {})

    def list(self, owner_id: int) -> list[dict[str, Any]]:
        prefix = self._storage_name("", owner_id)
        return [
            self._public(item["name"][len(prefix):], item)
            for item in self.db.list_secrets(limit=500, owner_id=int(owner_id))
            if str(item.get("name", "")).startswith(prefix)
        ]

    def reveal(self, owner_id: int, name: str) -> Optional[str]:
        record = self._owned(name, owner_id)
        if record is None:
            return None
        return self.security.decrypt(record["encrypted_value"])

    def delete(self, owner_id: int, name: str) -> bool:
        record = self._owned(name, owner_id)
        if record is None:
            return False
        return bool(self.db.delete_secret(record["id"]))

    @staticmethod
    def _public(name: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "description": record.get("description", ""),
            "updated_at": record.get("updated_at", ""),
        }
