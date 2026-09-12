from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import httpx


POLICY_PREFIX = "network_policy:"


@dataclass(frozen=True)
class NetworkPolicy:
    project_id: int
    profile_name: Optional[str] = None
    expected_public_ip: Optional[str] = None
    expected_country: Optional[str] = None
    require_vpn: bool = False
    fail_closed: bool = True
    verify_endpoint: str = "https://api.ipify.org?format=json"

    def validate(self) -> None:
        if self.project_id <= 0:
            raise ValueError("معرّف المشروع غير صالح.")
        if self.expected_public_ip and len(self.expected_public_ip) > 64:
            raise ValueError("عنوان IP المتوقع غير صالح.")
        if self.expected_country and len(self.expected_country) > 64:
            raise ValueError("رمز الدولة المتوقع غير صالح.")
        parsed = urlparse(self.verify_endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("نقطة التحقق يجب أن تكون HTTPS صالحة.")


class NetworkPolicyManager:
    def __init__(self, database, security, network_manager) -> None:
        self.db = database
        self.security = security
        self.network = network_manager
        self.network_manager = network_manager

    @staticmethod
    def _secret_name(project_id: int) -> str:
        return f"{POLICY_PREFIX}{project_id}"

    def save(self, policy: NetworkPolicy) -> dict[str, Any]:
        policy.validate()
        payload = json.dumps(asdict(policy), ensure_ascii=False)
        encrypted = self.security.encrypt(payload)
        name = self._secret_name(policy.project_id)
        existing = self.db.get_secret_by_name(name)
        if existing:
            self.db.update_secret(existing["id"], encrypted_value=encrypted, description="سياسة شبكة للمشروع")
        else:
            self.db.create_secret(name=name, encrypted_value=encrypted, description="سياسة شبكة للمشروع")
        return asdict(policy)

    def get(self, project_id: int) -> Optional[NetworkPolicy]:
        record = self.db.get_secret_by_name(self._secret_name(project_id))
        if not record:
            return None
        data = json.loads(self.security.decrypt(record["encrypted_value"]))
        policy = NetworkPolicy(
            project_id=int(data["project_id"]),
            profile_name=data.get("profile_name"),
            expected_public_ip=data.get("expected_public_ip"),
            expected_country=data.get("expected_country"),
            require_vpn=bool(data.get("require_vpn", False)),
            fail_closed=bool(data.get("fail_closed", True)),
            verify_endpoint=str(data.get("verify_endpoint", "https://api.ipify.org?format=json")),
        )
        policy.validate()
        return policy

    def delete(self, project_id: int) -> bool:
        record = self.db.get_secret_by_name(self._secret_name(project_id))
        if not record:
            return False
        return bool(self.db.delete_secret(record["id"]))

    async def verify_project(self, project_id: int) -> dict[str, Any]:
        policy = self.get(project_id)
        if policy is None:
            return {"configured": False, "allowed": True, "reason": "no_policy"}

        profile = None
        try:
            profile = self.network.get_profile(policy.profile_name) if policy.profile_name else self.network.get_project_profile(project_id)
            if policy.require_vpn and (profile is None or profile.mode != "proxy"):
                return {"configured": True, "allowed": False, "reason": "required_network_profile_missing"}

            proxy = profile.to_playwright_proxy() if profile else None
            proxy_url = None
            if proxy:
                proxy_url = proxy["server"]
                if proxy.get("username"):
                    parsed = urlparse(proxy_url)
                    host = parsed.hostname or ""
                    port = f":{parsed.port}" if parsed.port else ""
                    proxy_url = f"{parsed.scheme}://{proxy['username']}:{proxy.get('password', '')}@{host}{port}"

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, proxy=proxy_url) as client:
                response = await client.get(policy.verify_endpoint, headers={"User-Agent": "AutonomousBusinessManager/1.0"})
                response.raise_for_status()
                data = response.json()

            observed_ip = str(data.get("ip") or data.get("query") or "")
            observed_country = str(data.get("country_code") or data.get("country") or "").upper()
            ip_ok = not policy.expected_public_ip or observed_ip == policy.expected_public_ip
            country_ok = not policy.expected_country or observed_country == policy.expected_country.upper()
            allowed = bool(ip_ok and country_ok)
            reason = "ok" if allowed else "network_policy_mismatch"
            return {
                "configured": True,
                "allowed": allowed,
                "reason": reason,
                "observed_public_ip": observed_ip,
                "observed_country": observed_country,
                "profile": profile.masked() if profile else None,
            }
        except Exception as exc:
            return {
                "configured": True,
                "allowed": False,
                "reason": "verification_failed",
                "error_type": type(exc).__name__,
                "profile": profile.masked() if profile else None,
            }
