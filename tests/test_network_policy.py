import pytest

from app.network_policy import NetworkPolicy, NetworkPolicyManager


class FakeSecurity:
    def encrypt(self, value):
        return value

    def decrypt(self, value):
        return value


class FakeDB:
    def __init__(self):
        self.secrets = {}

    def get_secret_by_name(self, name):
        return self.secrets.get(name)

    def create_secret(self, **kwargs):
        record = {"id": len(self.secrets) + 1, **kwargs}
        self.secrets[kwargs["name"]] = record
        return record

    def update_secret(self, record_id, **kwargs):
        for name, record in self.secrets.items():
            if record["id"] == record_id:
                record.update(kwargs)
                return record
        return None

    def delete_secret(self, secret_id):
        for name, record in list(self.secrets.items()):
            if record["id"] == secret_id:
                del self.secrets[name]
                return True
        return False


class FakeProfile:
    mode = "proxy"

    def to_playwright_proxy(self):
        return {"server": "http://proxy.local:8080", "username": "u", "password": "SECRET"}

    def masked(self):
        return {"name": "p", "mode": "proxy", "proxy_server": "http://proxy.local:8080", "username": "u", "has_password": True, "bypass": ""}


class FakeNetwork:
    def __init__(self, profile=FakeProfile()):
        self.profile = profile

    def get_profile(self, name):
        return self.profile if name == "p" else None

    def get_project_profile(self, project_id):
        return self.profile


@pytest.mark.asyncio
async def test_matching_ip_and_country_allows(monkeypatch):
    manager = NetworkPolicyManager(FakeDB(), FakeSecurity(), FakeNetwork())
    manager.save(NetworkPolicy(1, profile_name="p", expected_public_ip="1.2.3.4", expected_country="YE"))

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"ip": "1.2.3.4", "country_code": "YE"}

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr("app.network_policy.httpx.AsyncClient", lambda **kwargs: Client())
    result = await manager.verify_project(1)
    assert result["allowed"] is True


@pytest.mark.asyncio
async def test_mismatch_blocks_when_fail_closed(monkeypatch):
    manager = NetworkPolicyManager(FakeDB(), FakeSecurity(), FakeNetwork())
    manager.save(NetworkPolicy(1, profile_name="p", expected_public_ip="9.9.9.9", fail_closed=True))

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"ip": "1.2.3.4"}

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr("app.network_policy.httpx.AsyncClient", lambda **kwargs: Client())
    result = await manager.verify_project(1)
    assert result["allowed"] is False
    assert result["reason"] == "network_policy_mismatch"


@pytest.mark.asyncio
async def test_verification_failure_blocks(monkeypatch):
    manager = NetworkPolicyManager(FakeDB(), FakeSecurity(), FakeNetwork())
    manager.save(NetworkPolicy(1, fail_closed=True))

    class Client:
        async def __aenter__(self): raise TimeoutError("offline")
        async def __aexit__(self, *args): pass

    monkeypatch.setattr("app.network_policy.httpx.AsyncClient", lambda **kwargs: Client())
    result = await manager.verify_project(1)
    assert result["allowed"] is False
    assert result["reason"] == "verification_failed"


@pytest.mark.asyncio
async def test_required_vpn_without_proxy_blocks():
    manager = NetworkPolicyManager(FakeDB(), FakeSecurity(), FakeNetwork(profile=None))
    manager.save(NetworkPolicy(1, require_vpn=True, fail_closed=True))
    result = await manager.verify_project(1)
    assert result["allowed"] is False
    assert result["reason"] == "required_network_profile_missing"


@pytest.mark.asyncio
async def test_no_policy_preserves_execution():
    manager = NetworkPolicyManager(FakeDB(), FakeSecurity(), FakeNetwork())
    result = await manager.verify_project(1)
    assert result == {"configured": False, "allowed": True, "reason": "no_policy"}


def test_policy_rejects_non_https_endpoint():
    with pytest.raises(ValueError):
        NetworkPolicy(1, verify_endpoint="http://example.com").validate()


def test_policy_delete_removes_encrypted_secret():
    db = FakeDB()
    manager = NetworkPolicyManager(db, FakeSecurity(), FakeNetwork())
    manager.save(NetworkPolicy(1, expected_country="YE"))

    assert manager.get(1) is not None
    assert manager.delete(1) is True
    assert manager.get(1) is None
    assert manager.delete(1) is False
