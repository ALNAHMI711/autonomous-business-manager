from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import httpx


PROFILE_PREFIX = "network_profile:"
BINDING_PREFIX = "network_binding:"
SUPPORTED_SCHEMES = {"http", "https", "socks5"}


@dataclass(frozen=True)
class NetworkProfile:
    name: str
    mode: str = "direct"
    proxy_server: str = ""
    username: str = ""
    password: str = ""
    bypass: str = ""

    def validate(self) -> None:
        if not self.name or len(self.name) > 80:
            raise ValueError("اسم ملف الشبكة غير صالح.")

        if self.mode not in {"direct", "proxy"}:
            raise ValueError("وضع الشبكة يجب أن يكون direct أو proxy.")

        if self.mode == "direct":
            return

        parsed = urlparse(self.proxy_server)
        if parsed.scheme.lower() not in SUPPORTED_SCHEMES:
            raise ValueError("البروكسي يجب أن يستخدم http أو https أو socks5.")
        if not parsed.hostname or not parsed.port:
            raise ValueError("عنوان البروكسي يجب أن يحتوي على المضيف وPort.")
        if parsed.username or parsed.password:
            raise ValueError("ضع اسم المستخدم وكلمة المرور في الحقول المخصصة.")

    def to_playwright_proxy(self) -> Optional[dict[str, str]]:
        self.validate()
        if self.mode == "direct":
            return None

        result: dict[str, str] = {
            "server": self.proxy_server,
        }
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        if self.bypass:
            result["bypass"] = self.bypass
        return result

    def masked(self) -> dict[str, Any]:
        self.validate()
        return {
            "name": self.name,
            "mode": self.mode,
            "proxy_server": self.proxy_server,
            "username": self.username,
            "has_password": bool(self.password),
            "bypass": self.bypass,
        }


class NetworkManager:
    """إدارة مسارات اتصال آمنة للمشاريع.

    direct: يستخدم مسار الشبكة الطبيعي للنظام (مثل إنترنت الهاتف عند تشغيل
    التطبيق على Termux).
    proxy: يوجه جلسة المتصفح عبر HTTP/HTTPS/SOCKS5 proxy محدد.

    هذا لا ينشئ VPN ولا يغير routing في نظام التشغيل؛ الـVPN الحقيقي يجب
    أن يكون مفعلاً على الجهاز نفسه. التطبيق يستطيع فقط اختيار proxy للمشروع.
    """

    def __init__(self, database, security) -> None:
        self.db = database
        self.security = security

    @staticmethod
    def _profile_secret_name(name: str) -> str:
        return f"{PROFILE_PREFIX}{name}"

    @staticmethod
    def _binding_secret_name(project_id: int) -> str:
        return f"{BINDING_PREFIX}{project_id}"

    def save_profile(self, profile: NetworkProfile) -> dict[str, Any]:
        profile.validate()
        payload = json.dumps(
            {
                "name": profile.name,
                "mode": profile.mode,
                "proxy_server": profile.proxy_server,
                "username": profile.username,
                "password": profile.password,
                "bypass": profile.bypass,
            },
            ensure_ascii=False,
        )
        encrypted = self.security.encrypt(payload)
        secret_name = self._profile_secret_name(profile.name)
        existing = self.db.get_secret_by_name(secret_name)

        if existing:
            record = self.db.update_secret(
                existing["id"],
                encrypted_value=encrypted,
                description="ملف اتصال شبكة للمشاريع والمتصفح",
            )
        else:
            record = self.db.create_secret(
                name=secret_name,
                encrypted_value=encrypted,
                description="ملف اتصال شبكة للمشاريع والمتصفح",
            )

        return profile.masked() | {"id": record.get("id") if record else None}

    def list_profiles(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self.db.list_secrets(limit=500):
            name = str(item.get("name", ""))
            if not name.startswith(PROFILE_PREFIX):
                continue
            profile_name = name[len(PROFILE_PREFIX):]
            try:
                profile = self.get_profile(profile_name)
                if profile:
                    result.append(profile.masked())
            except Exception:
                result.append({
                    "name": profile_name,
                    "mode": "invalid",
                    "proxy_server": "",
                    "username": "",
                    "has_password": False,
                    "bypass": "",
                })
        return result

    def get_profile(self, name: str) -> Optional[NetworkProfile]:
        record = self.db.get_secret_by_name(self._profile_secret_name(name))
        if not record:
            return None
        payload = self.security.decrypt(record["encrypted_value"])
        data = json.loads(payload)
        profile = NetworkProfile(
            name=str(data.get("name", name)),
            mode=str(data.get("mode", "direct")),
            proxy_server=str(data.get("proxy_server", "")),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            bypass=str(data.get("bypass", "")),
        )
        profile.validate()
        return profile

    def delete_profile(self, name: str) -> bool:
        record = self.db.get_secret_by_name(self._profile_secret_name(name))
        if not record:
            return False
        return bool(self.db.delete_secret(record["id"]))

    def bind_project(self, project_id: int, profile_name: Optional[str]) -> None:
        secret_name = self._binding_secret_name(project_id)
        existing = self.db.get_secret_by_name(secret_name)
        if not profile_name:
            if existing:
                self.db.delete_secret(existing["id"])
            return

        if not self.get_profile(profile_name):
            raise ValueError("ملف الشبكة المطلوب غير موجود.")

        encrypted = self.security.encrypt(profile_name)
        if existing:
            self.db.update_secret(existing["id"], encrypted_value=encrypted)
        else:
            self.db.create_secret(
                name=secret_name,
                encrypted_value=encrypted,
                description="ربط ملف شبكة بالمشروع",
            )

    def get_project_profile(self, project_id: int) -> Optional[NetworkProfile]:
        record = self.db.get_secret_by_name(self._binding_secret_name(project_id))
        if not record:
            return None
        profile_name = self.security.decrypt(record["encrypted_value"])
        return self.get_profile(profile_name)

    async def test_profile(self, profile_name: str) -> dict[str, Any]:
        profile = self.get_profile(profile_name)
        if not profile:
            raise ValueError("ملف الشبكة غير موجود.")

        proxy = profile.to_playwright_proxy()
        proxy_url = None
        if proxy:
            proxy_url = proxy["server"]
            if proxy.get("username"):
                parsed = urlparse(proxy_url)
                proxy_url = f"{parsed.scheme}://{proxy['username']}:{proxy.get('password', '')}@{parsed.hostname}:{parsed.port}"

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            proxy=proxy_url,
        ) as client:
            response = await client.get(
                "https://api.ipify.org?format=json",
                headers={"User-Agent": "AutonomousBusinessManager/1.0"},
            )
            response.raise_for_status()
            data = response.json()

        return {
            "success": True,
            "profile": profile.masked(),
            "observed_public_ip": str(data.get("ip", "")),
            "status_code": response.status_code,
        }
