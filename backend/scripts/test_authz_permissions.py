from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.alarm import AlarmActionLog
from app.models.alarm import AlarmEvent
from app.models.device import FSUDevice, MonitorPoint
from app.models.site import Site
from app.models.tenant import Tenant
from app.models.user import Role, User


class CheckFailed(RuntimeError):
    pass


def require(condition: bool, message: str):
    if not condition:
        raise CheckFailed(message)


def login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    require(resp.status_code == 200, f"login failed for {username}: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    suffix = uuid4().hex[:8]
    role_name = f"permtest_{suffix}"
    username = f"permuser_{suffix}"
    password = "perm123456"
    alarm_id: int | None = None
    role_id: int | None = None
    user_id: int | None = None

    with TestClient(app) as client:
        admin_token = login(client, "admin", "admin123")
        admin_headers = auth_headers(admin_token)

        meta_resp = client.get("/api/v1/users/meta", headers=admin_headers)
        require(meta_resp.status_code == 200, f"/users/meta failed: {meta_resp.status_code} {meta_resp.text}")
        permission_keys = {item["key"] for item in meta_resp.json()["permission_options"]}
        for key in [
            "alarm.ack",
            "alarm.close",
            "site.create",
            "site.update",
            "notify.channel.view",
            "notify.channel.manage",
            "notify.policy.view",
            "notify.policy.manage",
            "audit.view",
        ]:
            require(key in permission_keys, f"missing permission option: {key}")

        role_resp = client.post(
            "/api/v1/users/role-defs",
            headers=admin_headers,
            json={
                "name": role_name,
                "description": "权限回归测试角色",
                "permissions": ["site.view", "notify.channel.view"],
            },
        )
        require(role_resp.status_code == 200, f"create role failed: {role_resp.status_code} {role_resp.text}")
        role_id = role_resp.json()["id"]

        bind_role_resp = client.put(
            f"/api/v1/authz/roles/{role_id}/permissions",
            headers=admin_headers,
            json={"permission_keys": ["site.view", "notify.channel.view"]},
        )
        require(bind_role_resp.status_code == 200, f"bind role permissions failed: {bind_role_resp.status_code} {bind_role_resp.text}")
        role_permissions = set(bind_role_resp.json()["permissions"])
        require("site.view" in role_permissions, "role permissions missing site.view")
        require("notify.channel.view" in role_permissions, "role permissions missing notify.channel.view")
        require("site.create" not in role_permissions, "role permissions unexpectedly contain site.create")

        create_user_resp = client.post(
            "/api/v1/users",
            headers=admin_headers,
            json={
                "username": username,
                "password": password,
                "full_name": "权限回归用户",
                "role_names": [role_name],
                "tenant_roles": [{"tenant_code": "SUB-A", "role_name": role_name, "scope_level": "tenant"}],
                "data_scopes": [{"scope_type": "tenant", "scope_value": "SUB-A"}],
            },
        )
        require(create_user_resp.status_code == 200, f"create user failed: {create_user_resp.status_code} {create_user_resp.text}")
        user_id = create_user_resp.json()["id"]

        bind_scope_resp = client.put(
            f"/api/v1/authz/users/{user_id}/scopes",
            headers=admin_headers,
            json={"data_scopes": [{"scope_type": "site", "scope_value": "SITE-001"}]},
        )
        require(bind_scope_resp.status_code == 200, f"bind user scopes failed: {bind_scope_resp.status_code} {bind_scope_resp.text}")
        scope_items = bind_scope_resp.json()["data_scopes"]
        require(any(item["scope_type"] == "site" and item["scope_value"] == "SITE-001" for item in scope_items), "user scope update failed")

        user_token = login(client, username, password)
        user_headers = auth_headers(user_token)

        me_resp = client.get("/api/v1/auth/me", headers=user_headers)
        require(me_resp.status_code == 200, f"/auth/me failed: {me_resp.status_code} {me_resp.text}")
        me_data = me_resp.json()
        me_permissions = set(me_data["permissions"])
        require("site.view" in me_permissions, "auth/me missing site.view")
        require("notify.channel.view" in me_permissions, "auth/me missing notify.channel.view")
        require("site.create" not in me_permissions, "auth/me unexpectedly contains site.create")
        require(any(item["scope_type"] == "site" and item["scope_value"] == "SITE-001" for item in me_data["scopes"]), "auth/me missing site scope")

        sites_resp = client.get("/api/v1/sites", headers=user_headers)
        require(sites_resp.status_code == 200, f"list sites failed: {sites_resp.status_code} {sites_resp.text}")

        create_site_resp = client.post(
            "/api/v1/sites",
            headers=user_headers,
            json={"code": f"SITE-T-{suffix}", "name": "权限测试站点", "region": "测试区", "tenant_code": "SUB-A"},
        )
        require(create_site_resp.status_code == 403, f"site.create should be forbidden, got {create_site_resp.status_code}")

        notify_channels_resp = client.get("/api/v1/notify/channels", headers=user_headers)
        require(notify_channels_resp.status_code == 200, f"notify channels failed: {notify_channels_resp.status_code} {notify_channels_resp.text}")

        notify_policies_resp = client.get("/api/v1/notify/policies", headers=user_headers)
        require(notify_policies_resp.status_code == 403, f"notify policies should be forbidden, got {notify_policies_resp.status_code}")

        with SessionLocal() as db:
            site = db.scalar(select(Site).where(Site.code == "SITE-001"))
            require(site is not None, "SITE-001 not found")
            tenant = db.scalar(select(Tenant).where(Tenant.code == "SUB-A"))
            require(tenant is not None, "SUB-A tenant not found")
            device = db.scalar(select(FSUDevice).where(FSUDevice.site_id == site.id).order_by(FSUDevice.id.asc()))
            require(device is not None, "seed device not found")
            point = db.scalar(select(MonitorPoint).where(MonitorPoint.device_id == device.id).order_by(MonitorPoint.id.asc()))
            require(point is not None, "seed monitor point not found")
            alarm = AlarmEvent(
                site_id=site.id,
                device_id=device.id,
                point_id=point.id,
                alarm_code="perm_test_alarm",
                alarm_name="权限测试告警",
                alarm_level=2,
                status="active",
                trigger_value=1.0,
                content="权限测试告警",
                started_at=datetime.now(timezone.utc),
            )
            db.add(alarm)
            db.commit()
            db.refresh(alarm)
            alarm_id = alarm.id

        user_ack_resp = client.post(f"/api/v1/alarms/{alarm_id}/ack", headers=user_headers)
        require(user_ack_resp.status_code == 403, f"alarm.ack should be forbidden, got {user_ack_resp.status_code}")

        sub_token = login(client, "suba_noc", "noc12345")
        sub_headers = auth_headers(sub_token)
        sub_ack_resp = client.post(f"/api/v1/alarms/{alarm_id}/ack", headers=sub_headers)
        require(sub_ack_resp.status_code == 200, f"suba_noc ack failed: {sub_ack_resp.status_code} {sub_ack_resp.text}")

        with SessionLocal() as db:
            alarm = db.get(AlarmEvent, alarm_id)
            require(alarm is not None and alarm.status == "acknowledged", "alarm status not updated to acknowledged")

        print("result=PASS")

    if user_id or role_id or alarm_id:
        with SessionLocal() as db:
            if alarm_id:
                for log in db.scalars(select(AlarmActionLog).where(AlarmActionLog.alarm_id == alarm_id)).all():
                    db.delete(log)
                alarm = db.get(AlarmEvent, alarm_id)
                if alarm is not None:
                    db.delete(alarm)
            if user_id:
                user = db.get(User, user_id)
                if user is not None:
                    db.delete(user)
            if role_id:
                role = db.get(Role, role_id)
                if role is not None:
                    db.delete(role)
            db.commit()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailed as exc:
        print(f"result=FAIL detail={exc}")
        raise SystemExit(1)
