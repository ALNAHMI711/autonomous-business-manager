from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_store import AuthStore
from app.main import db, security, network_manager, _require_session
from app.network_policy import NetworkPolicy, NetworkPolicyManager
from app.security import hash_session_token
from app.ownership import OwnershipStore

router = APIRouter(prefix="/api/network-policy", tags=["network-policy"])
manager = NetworkPolicyManager(db, security, network_manager)
ownership = OwnershipStore(str(db.database_path))
auth_store = AuthStore(str(db.database_path))


class NetworkPolicyRequest(BaseModel):
    profile_name: str = Field(default="", max_length=80)
    expected_public_ip: str = Field(default="", max_length=64)
    expected_country: str = Field(default="", max_length=8)
    require_vpn: bool = False
    fail_closed: bool = True
    verify_endpoint: str = Field(default="https://api.ipify.org?format=json", max_length=500)


async def require_session(request: Request) -> str:
    return _require_session(request)


async def require_owned_project(project_id: int, request: Request, _: str = Depends(require_session)) -> int:
    if project_id <= 0 or db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="المشروع غير موجود.")
    token = request.cookies.get("session")
    user_id = auth_store.user_id(hash_session_token(token)) if token else None
    if user_id is None or not ownership.user_can_access_project(user_id, project_id):
        raise HTTPException(status_code=404, detail="المشروع غير موجود.")
    return project_id


@router.get("/{project_id}")
async def get_policy(project_id: int = Depends(require_owned_project)):
    policy = manager.get(project_id)
    return {"configured": policy is not None, "policy": policy.__dict__ if policy else None}


@router.put("/{project_id}")
async def save_policy(
    payload: NetworkPolicyRequest,
    project_id: int = Depends(require_owned_project),
):
    policy = NetworkPolicy(project_id=project_id, **payload.model_dump())
    manager.save(policy)
    db.create_event(
        event_type="network_policy_changed",
        message="تم تحديث سياسة الشبكة للمشروع.",
        project_id=project_id,
        metadata={"profile_name": policy.profile_name, "require_vpn": policy.require_vpn, "fail_closed": policy.fail_closed},
    )
    return {"ok": True, "policy": policy.__dict__}


@router.delete("/{project_id}")
async def delete_policy(project_id: int = Depends(require_owned_project)):
    manager.delete(project_id)
    db.create_event(event_type="network_policy_deleted", message="تم حذف سياسة الشبكة للمشروع.", project_id=project_id)
    return {"ok": True}


@router.post("/{project_id}/verify")
async def verify_policy(project_id: int = Depends(require_owned_project)):
    result = await manager.verify_project(project_id)
    return {"ok": True, **result}
