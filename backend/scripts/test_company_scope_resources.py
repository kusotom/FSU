from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.operation_log import OperationLog


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
    suffix = uuid4().hex[:8].upper()
    project_id: int | None = None
    device_group_id: int | None = None
    custom_scope_id: int | None = None
    batch_usernames = [f"batch_{suffix.lower()}_01", f"batch_{suffix.lower()}_02"]

    with TestClient(app) as client:
        admin_token = login(client, "admin", "admin123")
        admin_headers = auth_headers(admin_token)

        sub_token = login(client, "suba_noc", "noc12345")
        sub_headers = auth_headers(sub_token)

        hq_token = login(client, "hq_noc", "noc12345")
        hq_headers = auth_headers(hq_token)

        sites_resp = client.get("/api/v1/sites?tenant_code=SUB-A", headers=sub_headers)
        require(sites_resp.status_code == 200, f"list sites failed: {sites_resp.status_code} {sites_resp.text}")
        sites = sites_resp.json()
        require(bool(sites), "SUB-A has no sites")
        site_id = sites[0]["id"]

        create_project_resp = client.post(
            "/api/v1/projects?tenant_code=SUB-A",
            headers=sub_headers,
            json={"code": f"PROJ-{suffix}", "name": "项目资源回归测试"},
        )
        require(
            create_project_resp.status_code == 200,
            f"create project failed: {create_project_resp.status_code} {create_project_resp.text}",
        )
        project = create_project_resp.json()
        project_id = project["id"]
        require(project["code"] == f"PROJ-{suffix}", "project code mismatch")

        update_project_resp = client.put(
            f"/api/v1/projects/{project_id}?tenant_code=SUB-A",
            headers=sub_headers,
            json={"name": "项目资源回归测试-更新", "status": "active"},
        )
        require(
            update_project_resp.status_code == 200,
            f"update project failed: {update_project_resp.status_code} {update_project_resp.text}",
        )
        require(update_project_resp.json()["name"] == "项目资源回归测试-更新", "project update not applied")

        hq_create_project_resp = client.post(
            "/api/v1/projects?tenant_code=SUB-A",
            headers=hq_headers,
            json={"code": f"PROJ-X-{suffix}", "name": "总部不应创建成功"},
        )
        require(
            hq_create_project_resp.status_code == 403,
            f"hq_noc should not create project, got {hq_create_project_resp.status_code}",
        )

        create_group_resp = client.post(
            "/api/v1/device-groups?tenant_code=SUB-A",
            headers=sub_headers,
            json={
                "code": f"DG-{suffix}",
                "name": "设备组资源回归测试",
                "project_id": project_id,
                "site_id": site_id,
            },
        )
        require(
            create_group_resp.status_code == 200,
            f"create device group failed: {create_group_resp.status_code} {create_group_resp.text}",
        )
        device_group = create_group_resp.json()
        device_group_id = device_group["id"]

        list_groups_resp = client.get("/api/v1/device-groups?tenant_code=SUB-A", headers=sub_headers)
        require(
            list_groups_resp.status_code == 200,
            f"list device groups failed: {list_groups_resp.status_code} {list_groups_resp.text}",
        )
        require(any(item["id"] == device_group_id for item in list_groups_resp.json()), "device group not visible")

        create_scope_resp = client.post(
            "/api/v1/custom-scope-sets?tenant_code=SUB-A",
            headers=sub_headers,
            json={"name": f"重点站点-{suffix}", "resource_type": "site", "resource_ids": [site_id]},
        )
        require(
            create_scope_resp.status_code == 200,
            f"create custom scope failed: {create_scope_resp.status_code} {create_scope_resp.text}",
        )
        custom_scope = create_scope_resp.json()
        custom_scope_id = custom_scope["id"]
        require(custom_scope["item_count"] == 1, "custom scope item_count mismatch")

        update_scope_resp = client.put(
            f"/api/v1/custom-scope-sets/{custom_scope_id}?tenant_code=SUB-A",
            headers=sub_headers,
            json={"name": f"重点站点-{suffix}-更新", "resource_ids": [site_id]},
        )
        require(
            update_scope_resp.status_code == 200,
            f"update custom scope failed: {update_scope_resp.status_code} {update_scope_resp.text}",
        )
        require(update_scope_resp.json()["name"].endswith("更新"), "custom scope update not applied")

        batch_create_resp = client.post(
            "/api/v1/users/batch",
            headers=sub_headers,
            json={
                "items": [
                    {"username": batch_usernames[0], "full_name": "批量员工一"},
                    {"username": batch_usernames[1], "full_name": "批量员工二", "password": "batch123456"},
                ],
                "default_password": "batch123456",
                "on_existing": "skip",
                "role_names": ["operator"],
                "tenant_roles": [{"tenant_code": "SUB-A", "role_name": "operator"}],
                "data_scopes": [{"scope_type": "tenant", "scope_value": "SUB-A"}],
            },
        )
        require(
            batch_create_resp.status_code == 200,
            f"batch create users failed: {batch_create_resp.status_code} {batch_create_resp.text}",
        )
        require(batch_create_resp.json()["created_count"] == 2, "batch create count mismatch")
        require(batch_create_resp.json()["failed_count"] == 0, "batch create should not fail any item")
        require(batch_create_resp.json()["skipped_count"] == 0, "initial batch create should not skip any item")

        batch_skip_resp = client.post(
            "/api/v1/users/batch",
            headers=sub_headers,
            json={
                "items": [{"username": batch_usernames[0], "full_name": "批量员工一重复"}],
                "default_password": "batch123456",
                "on_existing": "skip",
                "role_names": ["operator"],
                "tenant_roles": [{"tenant_code": "SUB-A", "role_name": "operator"}],
                "data_scopes": [{"scope_type": "tenant", "scope_value": "SUB-A"}],
            },
        )
        require(
            batch_skip_resp.status_code == 200,
            f"batch skip users failed: {batch_skip_resp.status_code} {batch_skip_resp.text}",
        )
        require(batch_skip_resp.json()["created_count"] == 0, "batch skip should not create any item")
        require(batch_skip_resp.json()["skipped_count"] == 1, "batch skip count mismatch")

        batch_update_resp = client.post(
            "/api/v1/users/batch",
            headers=sub_headers,
            json={
                "items": [{"username": batch_usernames[1], "full_name": "批量员工二更新"}],
                "default_password": None,
                "on_existing": "update_name",
                "role_names": ["operator"],
                "tenant_roles": [{"tenant_code": "SUB-A", "role_name": "operator"}],
                "data_scopes": [{"scope_type": "tenant", "scope_value": "SUB-A"}],
            },
        )
        require(
            batch_update_resp.status_code == 200,
            f"batch update users failed: {batch_update_resp.status_code} {batch_update_resp.text}",
        )
        require(batch_update_resp.json()["updated_count"] == 1, "batch update count mismatch")

        batch_user_token = login(client, batch_usernames[0], "batch123456")
        batch_user_headers = auth_headers(batch_user_token)
        batch_me_resp = client.get("/api/v1/auth/me", headers=batch_user_headers)
        require(batch_me_resp.status_code == 200, f"batch user auth/me failed: {batch_me_resp.status_code} {batch_me_resp.text}")
        require(
            any(item["scope_type"] == "tenant" and item["scope_value"] == "SUB-A" for item in batch_me_resp.json()["scopes"]),
            "batch user missing tenant scope",
        )

        illegal_role_resp = client.post(
            "/api/v1/users/batch",
            headers=sub_headers,
            json={
                "items": [{"username": f"illegal_{suffix.lower()}", "full_name": "非法角色用户"}],
                "default_password": "batch123456",
                "role_names": ["admin"],
                "tenant_roles": [{"tenant_code": "SUB-A", "role_name": "admin"}],
                "data_scopes": [{"scope_type": "tenant", "scope_value": "SUB-A"}],
            },
        )
        require(
            illegal_role_resp.status_code == 403,
            f"tenant admin should not assign admin role, got {illegal_role_resp.status_code}",
        )

        list_logs_resp = client.get(
            "/api/v1/operation-logs?tenant_code=SUB-A",
            headers=sub_headers,
        )
        require(
            list_logs_resp.status_code == 200,
            f"list operation logs failed: {list_logs_resp.status_code} {list_logs_resp.text}",
        )
        log_items = list_logs_resp.json()
        require(isinstance(log_items, list), "operation logs response should be a list")
        require(
            any(item["action"] in {"user.batch_create", "project.create", "device_group.create", "custom_scope.create"} for item in log_items),
            "operation logs missing expected actions",
        )

        filtered_logs_resp = client.get(
            "/api/v1/operation-logs?tenant_code=SUB-A&action=user.batch_create&operator_keyword=suba",
            headers=sub_headers,
        )
        require(
            filtered_logs_resp.status_code == 200,
            f"filter operation logs failed: {filtered_logs_resp.status_code} {filtered_logs_resp.text}",
        )
        filtered_log_items = filtered_logs_resp.json()
        require(
            all(item["action"] == "user.batch_create" for item in filtered_log_items),
            "operation log action filter not applied",
        )

        export_logs_resp = client.get(
            "/api/v1/operation-logs/export?tenant_code=SUB-A&action=user.batch_create",
            headers=sub_headers,
        )
        require(
            export_logs_resp.status_code == 200,
            f"export operation logs failed: {export_logs_resp.status_code} {export_logs_resp.text}",
        )
        require("text/csv" in export_logs_resp.headers.get("content-type", ""), "operation logs export content-type mismatch")
        require("user.batch_create" in export_logs_resp.text, "operation logs export missing expected action")

        with SessionLocal() as db:
            has_batch_log = db.scalar(
                select(OperationLog.id).where(
                    OperationLog.action == "user.batch_create",
                    OperationLog.content.like("%成功 2 条%"),
                ).limit(1)
            )
            require(has_batch_log is not None, "batch create operation log missing")

        delete_scope_resp = client.delete(
            f"/api/v1/custom-scope-sets/{custom_scope_id}?tenant_code=SUB-A",
            headers=sub_headers,
        )
        require(
            delete_scope_resp.status_code == 200,
            f"delete custom scope failed: {delete_scope_resp.status_code} {delete_scope_resp.text}",
        )
        custom_scope_id = None

        delete_group_resp = client.delete(
            f"/api/v1/device-groups/{device_group_id}?tenant_code=SUB-A",
            headers=sub_headers,
        )
        require(
            delete_group_resp.status_code == 200,
            f"delete device group failed: {delete_group_resp.status_code} {delete_group_resp.text}",
        )
        device_group_id = None

        delete_project_resp = client.delete(
            f"/api/v1/projects/{project_id}?tenant_code=SUB-A",
            headers=sub_headers,
        )
        require(
            delete_project_resp.status_code == 200,
            f"delete project failed: {delete_project_resp.status_code} {delete_project_resp.text}",
        )
        project_id = None

        users_resp = client.get("/api/v1/users", headers=admin_headers)
        require(users_resp.status_code == 200, f"list users failed: {users_resp.status_code} {users_resp.text}")
        users = users_resp.json()
        updated_user = next((item for item in users if item["username"] == batch_usernames[1]), None)
        require(updated_user is not None, "updated batch user not found")
        require(updated_user["full_name"] == "批量员工二更新", "batch update name not applied")
        for username in batch_usernames:
            user = next((item for item in users if item["username"] == username), None)
            require(user is not None, f"batch user not found for cleanup: {username}")
            delete_resp = client.delete(f"/api/v1/users/{user['id']}", headers=admin_headers)
            require(delete_resp.status_code == 200, f"cleanup user failed: {delete_resp.status_code} {delete_resp.text}")

        print("result=PASS")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailed as exc:
        print(f"result=FAIL detail={exc}")
        raise SystemExit(1)
