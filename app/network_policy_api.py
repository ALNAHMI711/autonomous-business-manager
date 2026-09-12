from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.main import db, security, network_manager, _require_session
from app.network_policy import NetworkPolicy, NetworkPolicyManager

router = APIRouter(prefix="/api/network-policy", tags=["network-policy"])
manager = NetworkPolicyManager(db, security, network_manager)


class NetworkPolicyRequest(BaseModel):
    profile_name: str = Field(default="", max_length=80)
    expected_public_ip: str = Field(default="", max_length=64)
    expected_country: str = Field(default="", max_length=8)
    require_vpn: bool = False
    fail_closed: bool = True
    verify_endpoint: str = Field(default="https://api.ipify.org?format=json", max_length=500)


async def require_session(request: Request) -> str:
    return _require_session(request)


def _project_id(value: int) -> int:
    if value <= 0 or db.get_project(value) is None:
        raise HTTPException(status_code=404, detail="المشروع غير موجود.")
    return value


@router.get("/{project_id}", dependencies=[Depends(require_session)])
async def get_policy(project_id: int):
    project_id = _project_id(project_id)
    policy = manager.get(project_id)
    return {"configured": policy is not None, "policy": policy.__dict__ if policy else None}


@router.put("/{project_id}", dependencies=[Depends(require_session)])
async def save_policy(project_id: int, payload: NetworkPolicyRequest):
    project_id = _project_id(project_id)
    policy = NetworkPolicy(project_id=project_id, **payload.model_dump())
    manager.save(policy)
    db.create_event(
        event_type="network_policy_changed",
        message="تم تحديث سياسة الشبكة للمشروع.",
        project_id=project_id,
        metadata={"profile_name": policy.profile_name, "require_vpn": policy.require_vpn, "fail_closed": policy.fail_closed},
    )
    return {"ok": True, "policy": policy.__dict__}


@router.delete("/{project_id}", dependencies=[Depends(require_session)])
async def delete_policy(project_id: int):
    project_id = _project_id(project_id)
    manager.delete(project_id)
    db.create_event(event_type="network_policy_deleted", message="تم حذف سياسة الشبكة للمشروع.", project_id=project_id)
    return {"ok": True}


@router.post("/{project_id}/verify", dependencies=[Depends(require_session)])
async def verify_policy(project_id: int):
    project_id = _project_id(project_id)
    result = await manager.verify_project(project_id)
    return {"ok": True, **result}
