import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.site import Site
from app.models.tenant import Tenant, UserTenantRole
from app.models.user import Role, RolePermission, User, UserDataScope, user_roles
from app.schemas.tenant import UserTenantRoleAssign, UserTenantRoleView
from app.schemas.user import (
    RoleDefCreate,
    RoleDefResponse,
    RoleDefUpdate,
    UserCreate,
    UserDataScopeAssign,
    UserDataScopeView,
    UserMetaResponse,
    UserResponse,
    UserUpdate,
)
from app.services.access_control import (
    BUILTIN_ROLE_DEFAULT_PERMISSIONS,
    HQ_TENANT_CODE,
    PERMISSION_KEY_SET,
    SCOPE_TYPE_SET,
    get_permission_options,
    get_role_permissions,
    get_scope_type_options,
)

router = APIRouter(prefix="/users", tags=["users"])
BUILTIN_ROLE_NAMES = {"admin", "operator", "hq_noc", "sub_noc"}


def _normalize_role_name(value: str) -> str:
    name = value.strip().lower()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色名称不能为空")
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
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"租户不存在：{scope_value}")
            normalized[(scope_type, tenant.code)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=tenant.code,
                scope_name=tenant.name,
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

        if scope_type == "region":
            region_exists = db.scalar(select(Site.id).where(Site.region == scope_value).limit(1))
            if region_exists is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"区域不存在：{scope_value}")
            normalized[(scope_type, scope_value)] = UserDataScopeView(
                scope_type=scope_type,
                scope_value=scope_value,
                scope_name=scope_value,
            )

    for item in payload_tenant_roles:
        tenant_code = str(item.tenant_code or "").strip()
        if not tenant_code:
            continue
        tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"租户不存在：{tenant_code}")
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
def list_users(db: Session = Depends(get_db), _=Depends(require_admin)):
    users = list(db.scalars(select(User).order_by(User.id.desc())).all())
    return [_to_response(item) for item in users]


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
    _=Depends(require_admin),
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
    data_scopes = _normalize_user_data_scopes(db, payload.data_scopes, payload.tenant_roles)

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
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item = db.get(User, user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

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
    data_scopes = _normalize_user_data_scopes(db, payload.data_scopes, payload.tenant_roles)

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
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.delete("/{user_id}", response_model=dict[str, str])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    item = db.get(User, user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前登录用户")

    db.delete(item)
    db.commit()
    return {"message": "用户已删除"}
