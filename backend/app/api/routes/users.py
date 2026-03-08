import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.deps_authz import get_access_context
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.custom_scope import CustomScopeSet
from app.models.device_group import DeviceGroup
from app.models.project import Project
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding, UserTenantRole
from app.models.user import Role, RolePermission, User, UserDataScope, user_roles
from app.schemas.tenant import UserTenantRoleAssign, UserTenantRoleView
from app.schemas.user import (
    RoleDefCreate,
    RoleDefResponse,
    RoleDefUpdate,
    UserBatchCreate,
    UserBatchCreateResponse,
    UserCreate,
    UserDataScopeAssign,
    UserDataScopeView,
    UserMetaResponse,
    UserResponse,
    UserUpdate,
)
from app.services.access_control import (
    AccessContext,
    BUILTIN_ROLE_DEFAULT_PERMISSIONS,
    HQ_TENANT_CODE,
    PERMISSION_KEY_SET,
    SCOPE_TYPE_SET,
    get_permission_options,
    get_role_permissions,
    get_scope_type_options,
)
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/users", tags=["users"])
BUILTIN_ROLE_NAMES = {"admin", "operator", "hq_noc", "sub_noc"}


def _normalize_role_name(value: str) -> str:
    name = value.strip().lower()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色标识不能为空")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色标识仅支持小写字母、数字、下划线，且必须以字母开头，长度 2-64 位",
        )
    return name


def _clean_permission_keys(items: list[str]) -> list[str]:
    keys = sorted({str(item or "").strip() for item in items if str(item or "").strip()})
    invalid = [item for item in keys if item not in PERMISSION_KEY_SET]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"存在未定义的功能权限：{'、'.join(invalid)}",
        )
    return keys


def _normalize_user_data_scopes(
    db: Session,
    payload_scopes: list[UserDataScopeAssign],
    payload_tenant_roles: list[UserTenantRoleAssign],
) -> list[UserDataScopeView]:
    normalized: dict[tuple[str, str], UserDataScopeView] = {}

    for item in payload_scopes:
        scope_type = str(item.scope_type or "").strip().lower()
        scope_value = str(item.scope_value or "").strip()
        if scope_type not in SCOPE_TYPE_SET:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持的数据范围类型：{scope_type}")

        if scope_type == "all":
            normalized[("all", "*")] = UserDataScopeView(
                scope_type="all",
                scope_value="*",
                scope_name="全部数据",
            )
            continue

        if not scope_value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据范围值不能为空")

        if scope_type == "tenant":
            tenant = db.scalar(select(Tenant).where(Tenant.code == scope_value))
            if tenant is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"公司不存在：{scope_value}")
            normalized[(scope_type, tenant.code)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=tenant.code,
                scope_name=tenant.name,
            )
            continue

        if scope_type == "project":
            project = db.scalar(select(Project).where(Project.code == scope_value))
            if project is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"项目不存在：{scope_value}")
            normalized[(scope_type, project.code)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=project.code,
                scope_name=project.name,
            )
            continue

        if scope_type == "site":
            site = db.scalar(select(Site).where(Site.code == scope_value))
            if site is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"站点不存在：{scope_value}")
            normalized[(scope_type, site.code)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=site.code,
                scope_name=site.name,
            )
            continue

        if scope_type == "device_group":
            device_group = db.scalar(select(DeviceGroup).where(DeviceGroup.code == scope_value))
            if device_group is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"设备组不存在：{scope_value}")
            normalized[(scope_type, device_group.code)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=device_group.code,
                scope_name=device_group.name,
            )
            continue

        if scope_type == "region":
            region_exists = db.scalar(select(Site.id).where(Site.region == scope_value).limit(1))
            if region_exists is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"区域不存在：{scope_value}")
            normalized[(scope_type, scope_value)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=scope_value,
                scope_name=scope_value,
            )
            continue

        if scope_type == "custom":
            try:
                scope_id = int(scope_value)
            except (TypeError, ValueError):
                scope_id = 0
            custom_scope = db.scalar(select(CustomScopeSet).where(CustomScopeSet.id == scope_id))
            if custom_scope is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"自定义范围不存在：{scope_value}")
            normalized[(scope_type, str(custom_scope.id))] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=str(custom_scope.id),
                scope_name=custom_scope.name,
            )

    for item in payload_tenant_roles:
        tenant_code = str(item.tenant_code or "").strip()
        if not tenant_code:
            continue
        tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"公司不存在：{tenant_code}")
        normalized[("tenant", tenant.code)] = UserDataScopeView(
            scope_type="tenant",
            scope_value=tenant.code,
            scope_name=tenant.name,
        )

    scopes = list(normalized.values())
    if not scopes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少配置一个数据范围")
    if any(item.scope_type == "all" for item in scopes):
        return [UserDataScopeView(scope_type="all", scope_value="*", scope_name="全部数据")]
    return sorted(scopes, key=lambda item: (item.scope_type, item.scope_value))


def _resolve_roles(db: Session, role_names_input: list[str]) -> list[Role]:
    role_names = sorted({str(name or "").strip() for name in role_names_input if str(name or "").strip()})
    if not role_names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少指定一个角色")
    roles = list(db.scalars(select(Role).where(Role.name.in_(role_names))).all())
    role_map = {item.name: item for item in roles}
    if len(role_map) != len(role_names):
        missing = [name for name in role_names if name not in role_map]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"存在未定义的角色：{'、'.join(missing)}",
    )
    return sorted(roles, key=lambda item: item.name)


def _tenant_codes_for_scopes(db: Session, data_scopes: list[UserDataScopeView]) -> set[str]:
    tenant_codes: set[str] = set()
    for item in data_scopes:
        if item.scope_type == "all":
            tenant_codes.add("*")
            continue

        if item.scope_type == "tenant":
            tenant_codes.add(item.scope_value)
            continue

        if item.scope_type == "project":
            project = db.scalar(select(Project).where(Project.code == item.scope_value))
            if project is not None:
                tenant = db.get(Tenant, project.tenant_id)
                if tenant is not None:
                    tenant_codes.add(tenant.code)
            continue

        if item.scope_type == "site":
            rows = db.execute(
                select(Tenant.code)
                .join(TenantSiteBinding, TenantSiteBinding.tenant_id == Tenant.id)
                .join(Site, Site.id == TenantSiteBinding.site_id)
                .where(Site.code == item.scope_value)
            ).all()
            tenant_codes.update(code for code, in rows if code)
            continue

        if item.scope_type == "device_group":
            device_group = db.scalar(select(DeviceGroup).where(DeviceGroup.code == item.scope_value))
            if device_group is not None:
                tenant = db.get(Tenant, device_group.tenant_id)
                if tenant is not None:
                    tenant_codes.add(tenant.code)
            continue

        if item.scope_type == "custom":
            try:
                scope_id = int(item.scope_value)
            except (TypeError, ValueError):
                scope_id = 0
            if scope_id:
                custom_scope = db.get(CustomScopeSet, scope_id)
                if custom_scope is not None:
                    tenant = db.get(Tenant, custom_scope.tenant_id)
                    if tenant is not None:
                        tenant_codes.add(tenant.code)
            continue

        if item.scope_type == "region":
            rows = db.execute(
                select(Tenant.code)
                .join(TenantSiteBinding, TenantSiteBinding.tenant_id == Tenant.id)
                .join(Site, Site.id == TenantSiteBinding.site_id)
                .where(Site.region == item.scope_value)
            ).all()
            tenant_codes.update(code for code, in rows if code)

    return tenant_codes


def _assert_tenant_scope_allowed(
    db: Session,
    access: AccessContext,
    data_scopes: list[UserDataScopeView],
    tenant_roles: list[UserTenantRoleAssign],
):
    if access.can_global_read:
        return

    if any(item.scope_type == "all" for item in data_scopes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司账号")

    requested_tenant_codes = {item.tenant_code for item in tenant_roles if item.tenant_code}
    requested_tenant_codes.update(_tenant_codes_for_scopes(db, data_scopes))

    if not requested_tenant_codes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少公司范围")

    if not requested_tenant_codes.issubset(access.tenant_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司账号")


def _assert_assignable_roles(access: AccessContext, roles: list[Role]):
    if access.can_global_read:
        return
    forbidden = [item.name for item in roles if item.name in {"admin", "hq_noc"}]
    if forbidden:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能分配平台级角色")


def _user_tenant_codes(db: Session, user: User) -> set[str]:
    codes = {item.tenant.code for item in user.tenant_roles if item.tenant and item.tenant.code}
    if not codes:
        scopes = _to_response(user).data_scopes
        codes.update(code for code in _tenant_codes_for_scopes(db, scopes) if code != "*")
    return codes


def _assert_manageable_user(db: Session, access: AccessContext, user: User):
    if access.can_global_read:
        return
    target_codes = _user_tenant_codes(db, user)
    if not target_codes or not target_codes.issubset(access.tenant_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司账号")


def _sync_role_permissions(db: Session, role: Role, permission_keys: list[str]):
    existing = {item.permission_key: item for item in role.permissions}
    expected = set(permission_keys)
    for key, item in existing.items():
        if key not in expected:
            db.delete(item)
    for key in permission_keys:
        if key in existing:
            continue
        db.add(RolePermission(role_id=role.id, permission_key=key))


def _sync_user_tenant_roles(
    db: Session,
    *,
    user: User,
    roles: list[Role],
    data_scopes: list[UserDataScopeView],
):
    user.tenant_roles.clear()
    db.flush()

    tenant_scope_codes = [item.scope_value for item in data_scopes if item.scope_type == "tenant"]
    if any(item.scope_type == "all" for item in data_scopes):
        tenant_scope_codes = [HQ_TENANT_CODE]
    if not tenant_scope_codes:
        return

    tenants = list(db.scalars(select(Tenant).where(Tenant.code.in_(tenant_scope_codes))).all())
    tenant_map = {item.code: item for item in tenants}
    for tenant_code in tenant_scope_codes:
        tenant = tenant_map.get(tenant_code)
        if tenant is None:
            continue
        for role in roles:
            db.add(
                UserTenantRole(
                    user_id=user.id,
                    role_id=role.id,
                    tenant_id=tenant.id,
                    scope_level="tenant",
                )
            )


def _sync_user_data_scopes(db: Session, user: User, scopes: list[UserDataScopeView]):
    for item in list(user.data_scopes):
        db.delete(item)
    db.flush()
    for item in scopes:
        user.data_scopes.append(
            UserDataScope(
                scope_type=item.scope_type,
                scope_value=item.scope_value,
                scope_name=item.scope_name,
            )
        )


def _to_response(user: User) -> UserResponse:
    tenant_roles = [
        UserTenantRoleView(
            tenant_code=item.tenant.code,
            tenant_name=item.tenant.name,
            tenant_type=item.tenant.tenant_type,
            role_name=item.role.name,
            scope_level=item.scope_level,
        )
        for item in sorted(user.tenant_roles, key=lambda x: (x.tenant.code, x.role.name, x.id))
    ]
    permissions = sorted({key for role in user.roles for key in get_role_permissions(role)})
    data_scopes = [
        UserDataScopeView(
            scope_type=item.scope_type,
            scope_value=item.scope_value,
            scope_name=item.scope_name,
        )
        for item in sorted(user.data_scopes, key=lambda x: (x.scope_type, x.scope_value, x.id))
    ]
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        roles=sorted({role.name for role in user.roles}),
        permissions=permissions,
        tenant_roles=tenant_roles,
        data_scopes=data_scopes,
    )


def _role_def_response(item: Role) -> RoleDefResponse:
    return RoleDefResponse(
        id=item.id,
        name=item.name,
        description=item.description,
        is_builtin=item.name in BUILTIN_ROLE_NAMES,
        permissions=sorted(get_role_permissions(item)),
    )


@router.get("/meta", response_model=UserMetaResponse)
def get_user_meta(_=Depends(require_admin)):
    return UserMetaResponse(
        permission_options=get_permission_options(),
        scope_type_options=get_scope_type_options(),
    )


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_admin),
    access: AccessContext = Depends(get_access_context),
):
    users = list(db.scalars(select(User).order_by(User.id.desc())).all())
    if access.can_global_read:
        return [_to_response(item) for item in users]
    return [_to_response(item) for item in users if _user_tenant_codes(db, item).issubset(access.tenant_codes)]


@router.get("/roles", response_model=list[str])
def list_roles(db: Session = Depends(get_db), _=Depends(require_admin)):
    rows = list(db.scalars(select(Role.name).order_by(Role.name.asc())).all())
    return sorted({item for item in rows if item})


@router.get("/role-defs", response_model=list[RoleDefResponse])
def list_role_defs(db: Session = Depends(get_db), _=Depends(require_admin)):
    rows = list(db.scalars(select(Role).order_by(Role.name.asc())).all())
    return [_role_def_response(item) for item in rows]


@router.post("/role-defs", response_model=RoleDefResponse)
def create_role_def(
    payload: RoleDefCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    role_name = _normalize_role_name(payload.name)
    exists = db.scalar(select(Role).where(Role.name == role_name))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="角色已存在")

    permission_keys = _clean_permission_keys(payload.permissions)
    item = Role(name=role_name, description=(payload.description or "").strip() or None)
    db.add(item)
    db.flush()
    _sync_role_permissions(db, item, permission_keys)
    db.commit()
    db.refresh(item)
    return _role_def_response(item)


@router.put("/role-defs/{role_id}", response_model=RoleDefResponse)
def update_role_def(
    role_id: int,
    payload: RoleDefUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    item = db.get(Role, role_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")

    new_name = _normalize_role_name(payload.name)
    if item.name in BUILTIN_ROLE_NAMES and new_name != item.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内置角色不允许修改标识")
    if new_name != item.name:
        exists = db.scalar(select(Role).where(Role.name == new_name))
        if exists is not None and exists.id != item.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="角色标识已存在")
        item.name = new_name

    permission_keys = _clean_permission_keys(payload.permissions)
    if item.name in BUILTIN_ROLE_NAMES and set(permission_keys) != BUILTIN_ROLE_DEFAULT_PERMISSIONS[item.name]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内置角色权限由系统维护，不允许手工修改")

    item.description = (payload.description or "").strip() or None
    _sync_role_permissions(db, item, permission_keys)
    db.commit()
    db.refresh(item)
    return _role_def_response(item)


@router.delete("/role-defs/{role_id}", response_model=dict[str, str])
def delete_role_def(
    role_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    item = db.get(Role, role_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
    if item.name in BUILTIN_ROLE_NAMES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内置角色不允许删除")

    user_role_ref_count = int(
        db.scalar(select(func.count()).select_from(user_roles).where(user_roles.c.role_id == role_id)) or 0
    )
    tenant_role_ref_count = int(
        db.scalar(select(func.count(UserTenantRole.id)).where(UserTenantRole.role_id == role_id)) or 0
    )
    if user_role_ref_count > 0 or tenant_role_ref_count > 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色已被用户引用，不能删除")

    db.delete(item)
    db.commit()
    return {"message": "角色已删除"}


@router.post("", response_model=UserResponse)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    access: AccessContext = Depends(get_access_context),
):
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名不能为空")
    if len(username) < 3 or len(username) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名长度必须在 3-64 位之间")
    if len(payload.password or "") < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码长度至少 6 位")

    exists = db.scalar(select(User).where(User.username == username))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    roles = _resolve_roles(db, payload.role_names)
    _assert_assignable_roles(access, roles)
    data_scopes = _normalize_user_data_scopes(db, payload.data_scopes, payload.tenant_roles)
    _assert_tenant_scope_allowed(db, access, data_scopes, payload.tenant_roles)

    item = User(
        username=username,
        password_hash=get_password_hash(payload.password),
        full_name=(payload.full_name or "").strip() or None,
        is_active=True,
    )
    item.roles = roles
    db.add(item)
    db.flush()
    _sync_user_data_scopes(db, item, data_scopes)
    _sync_user_tenant_roles(db, user=item, roles=roles, data_scopes=data_scopes)
    primary_tenant_code = next((scope.scope_value for scope in data_scopes if scope.scope_type == "tenant"), None)
    tenant = db.scalar(select(Tenant).where(Tenant.code == primary_tenant_code)) if primary_tenant_code else None
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id if tenant else None,
        action="user.create",
        target_type="user",
        target_id=str(item.id),
        content=f"创建用户 {item.username}，角色={','.join(role.name for role in roles)}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.post("/batch", response_model=UserBatchCreateResponse)
def batch_create_users(
    payload: UserBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    access: AccessContext = Depends(get_access_context),
):
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少提供一条用户记录")

    roles = _resolve_roles(db, payload.role_names)
    _assert_assignable_roles(access, roles)
    data_scopes = _normalize_user_data_scopes(db, payload.data_scopes, payload.tenant_roles)
    _assert_tenant_scope_allowed(db, access, data_scopes, payload.tenant_roles)

    default_password = str(payload.default_password or "")
    if default_password and len(default_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="默认密码长度至少 6 位")
    on_existing = str(payload.on_existing or "skip").strip().lower()
    if on_existing not in {"skip", "update_name", "reset_password"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的已存在账号处理策略")

    seen_usernames: set[str] = set()
    created_usernames: list[str] = []
    created_items: list[dict] = []
    updated_items: list[dict] = []
    skipped_items: list[dict] = []
    failed_items: list[dict] = []
    primary_tenant_code = next((scope.scope_value for scope in data_scopes if scope.scope_type == "tenant"), None)
    tenant = db.scalar(select(Tenant).where(Tenant.code == primary_tenant_code)) if primary_tenant_code else None

    for row in payload.items:
        username = (row.username or "").strip()
        full_name = (row.full_name or "").strip() or None
        password = str(row.password or "").strip() or default_password

        if not username:
            failed_items.append({"username": "", "message": "用户名不能为空"})
            continue
        if len(username) < 3 or len(username) > 64:
            failed_items.append({"username": username, "message": "用户名长度必须在 3-64 位之间"})
            continue
        if username in seen_usernames:
            failed_items.append({"username": username, "message": "批量数据中用户名重复"})
            continue
        exists = db.scalar(select(User).where(User.username == username))
        if exists is not None:
            if on_existing == "skip":
                skipped_items.append({"username": username, "message": "用户名已存在，已跳过"})
                continue
            _assert_manageable_user(db, access, exists)
            if on_existing == "update_name":
                exists.full_name = full_name
                updated_items.append({"username": username, "message": "已更新姓名"})
                write_operation_log(
                    db,
                    operator_id=current_user.id,
                    tenant_id=tenant.id if tenant else None,
                    action="user.batch_update_item",
                    target_type="user",
                    target_id=str(exists.id),
                    content=f"批量更新用户 {username}，更新项=full_name",
                )
                continue
            if len(password) < 6:
                failed_items.append({"username": username, "message": "更新密码时缺少有效密码，且默认密码不可用"})
                continue
            exists.full_name = full_name
            exists.password_hash = get_password_hash(password)
            updated_items.append({"username": username, "message": "已更新姓名并重置密码"})
            write_operation_log(
                db,
                operator_id=current_user.id,
                tenant_id=tenant.id if tenant else None,
                action="user.batch_update_item",
                target_type="user",
                target_id=str(exists.id),
                content=f"批量更新用户 {username}，更新项=full_name,password",
            )
            continue
        if len(password) < 6:
            failed_items.append({"username": username, "message": "缺少有效密码，且默认密码不可用"})
            continue

        seen_usernames.add(username)
        item = User(
            username=username,
            password_hash=get_password_hash(password),
            full_name=full_name,
            is_active=True,
        )
        item.roles = roles
        db.add(item)
        db.flush()
        _sync_user_data_scopes(db, item, data_scopes)
        _sync_user_tenant_roles(db, user=item, roles=roles, data_scopes=data_scopes)
        created_usernames.append(username)
        created_items.append({"username": username, "message": "创建成功"})
        write_operation_log(
            db,
            operator_id=current_user.id,
            tenant_id=tenant.id if tenant else None,
            action="user.batch_create_item",
            target_type="user",
            target_id=str(item.id),
            content=f"批量创建用户 {username}，角色={','.join(role.name for role in roles)}",
        )

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id if tenant else None,
        action="user.batch_create",
        target_type="user_batch",
        target_id=primary_tenant_code or None,
        content=(
            f"批量创建员工：成功 {len(created_items)} 条，"
            f"更新 {len(updated_items)} 条，跳过 {len(skipped_items)} 条，失败 {len(failed_items)} 条"
        ),
    )
    db.commit()
    return UserBatchCreateResponse(
        created_count=len(created_usernames),
        updated_count=len(updated_items),
        skipped_count=len(skipped_items),
        failed_count=len(failed_items),
        usernames=created_usernames,
        created_items=created_items,
        updated_items=updated_items,
        skipped_items=skipped_items,
        failed_items=failed_items,
    )


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    access: AccessContext = Depends(get_access_context),
):
    item = db.get(User, user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    _assert_manageable_user(db, access, item)

    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名不能为空")
    if len(username) < 3 or len(username) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名长度必须在 3-64 位之间")

    exists = db.scalar(select(User).where(User.username == username, User.id != user_id))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    if not payload.is_active and current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用当前登录用户")

    roles = _resolve_roles(db, payload.role_names)
    _assert_assignable_roles(access, roles)
    data_scopes = _normalize_user_data_scopes(db, payload.data_scopes, payload.tenant_roles)
    _assert_tenant_scope_allowed(db, access, data_scopes, payload.tenant_roles)

    item.username = username
    item.full_name = (payload.full_name or "").strip() or None
    item.is_active = payload.is_active
    item.roles = roles
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码长度至少 6 位")
        item.password_hash = get_password_hash(payload.password)

    _sync_user_data_scopes(db, item, data_scopes)
    _sync_user_tenant_roles(db, user=item, roles=roles, data_scopes=data_scopes)
    primary_tenant_code = next((scope.scope_value for scope in data_scopes if scope.scope_type == "tenant"), None)
    tenant = db.scalar(select(Tenant).where(Tenant.code == primary_tenant_code)) if primary_tenant_code else None
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id if tenant else None,
        action="user.update",
        target_type="user",
        target_id=str(item.id),
        content=f"更新用户 {item.username}，角色={','.join(role.name for role in roles)}，状态={'启用' if item.is_active else '停用'}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.delete("/{user_id}", response_model=dict[str, str])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    access: AccessContext = Depends(get_access_context),
):
    item = db.get(User, user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前登录用户")
    _assert_manageable_user(db, access, item)

    target_tenant_code = next((row.tenant.code for row in item.tenant_roles if row.tenant), None)
    tenant = db.scalar(select(Tenant).where(Tenant.code == target_tenant_code)) if target_tenant_code else None
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id if tenant else None,
        action="user.delete",
        target_type="user",
        target_id=str(item.id),
        content=f"删除用户 {item.username}",
    )
    db.delete(item)
    db.commit()
    return {"message": "用户已删除"}
