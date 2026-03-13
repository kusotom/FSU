import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, require_user_manager
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.device_group import DeviceGroup
from app.models.site import Site
from app.models.tenant import Tenant, UserTenantRole
from app.models.user import Role, RolePermission, User, UserDataScope
from app.schemas.tenant import UserTenantRoleView
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
    CORE_ROLE_COMPANY,
    CORE_ROLE_DEFINITIONS,
    CORE_ROLE_EMPLOYEE,
    CORE_ROLE_PLATFORM,
    CORE_ROLE_SET,
    AccessContext,
    get_core_role_options,
    get_default_permissions_for_core_role,
    get_permission_options,
    get_permission_templates,
    get_role_permissions,
    get_scope_type_options,
    get_tenant_for_site,
    get_user_core_role,
    match_template_key,
    normalize_assignable_permissions,
    resolve_template_permissions,
    simplify_permissions,
)
from app.services.auth_sms import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DISABLED,
    USER_STATUS_PENDING,
    normalize_phone,
)
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/users", tags=["users"])

CORE_ROLE_LABELS = {item.key: item.label for item in CORE_ROLE_DEFINITIONS}
CORE_ROLE_ROLE_NAMES = {
    CORE_ROLE_PLATFORM: CORE_ROLE_PLATFORM,
    CORE_ROLE_COMPANY: CORE_ROLE_COMPANY,
    CORE_ROLE_EMPLOYEE: CORE_ROLE_EMPLOYEE,
}


def _normalize_username(username: str | None, fallback_phone: str | None = None) -> str:
    value = str(username or "").strip()
    if not value:
        value = fallback_phone or ""
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名不能为空")
    if len(value) < 3 or len(value) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名长度必须在 3-64 位之间")
    return value


def _normalize_password(password: str | None, *, required: bool) -> str | None:
    value = str(password or "").strip()
    if not value:
        if required:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码不能为空")
        return None
    if len(value) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码长度至少 6 位")
    return value


def _normalize_phone_input(phone_country_code: str | None, phone: str | None) -> tuple[str, str]:
    country_code, normalized_phone = normalize_phone(phone_country_code, phone)
    if not normalized_phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手机号不能为空")
    if len(normalized_phone) < 6 or len(normalized_phone) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手机号格式不正确")
    return country_code, normalized_phone


def _normalize_core_role(core_role: str | None, fallback_roles: list[str]) -> str:
    value = str(core_role or "").strip()
    if not value:
        value = get_user_core_role(fallback_roles)
    if value not in CORE_ROLE_SET:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的核心角色")
    return value


def _resolve_core_role(db: Session, core_role: str) -> Role:
    role_name = CORE_ROLE_ROLE_NAMES[core_role]
    role = db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        role = Role(name=role_name, description=CORE_ROLE_LABELS[core_role])
        db.add(role)
        db.flush()
    if role.description != CORE_ROLE_LABELS[core_role]:
        role.description = CORE_ROLE_LABELS[core_role]
    return role


def _permission_role_name(user_id: int) -> str:
    return f"user_perm_{user_id}"


def _resolve_permission_role(db: Session, user_id: int) -> Role:
    role_name = _permission_role_name(user_id)
    role = db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        role = Role(name=role_name, description=f"用户权限角色#{user_id}")
        db.add(role)
        db.flush()
    return role


def _sync_role_permissions(db: Session, role: Role, permission_keys: list[str]) -> None:
    existing = {item.permission_key: item for item in role.permissions}
    expected = set(permission_keys)
    for key, item in existing.items():
        if key not in expected:
            db.delete(item)
    for key in permission_keys:
        if key in existing:
            continue
        db.add(RolePermission(role_id=role.id, permission_key=key))


def _tenant_from_code(db: Session, tenant_code: str | None) -> Tenant | None:
    code = str(tenant_code or "").strip()
    if not code:
        return None
    return db.scalar(select(Tenant).where(Tenant.code == code))


def _access_default_tenant(db: Session, access: AccessContext) -> Tenant | None:
    if not access.tenant_codes:
        return None
    code = sorted(access.tenant_codes)[0]
    return _tenant_from_code(db, code)


def _resolve_target_tenant(
    db: Session,
    access: AccessContext,
    *,
    core_role: str,
    tenant_code: str | None,
) -> Tenant | None:
    tenant = _tenant_from_code(db, tenant_code)
    if access.is_platform_admin:
        if core_role == CORE_ROLE_PLATFORM:
            return None
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择所属公司")
        if tenant.code == "HQ-GROUP":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司管理员和员工必须归属具体公司")
        return tenant

    if not access.is_company_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权管理用户")

    own_tenant = _access_default_tenant(db, access)
    if own_tenant is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前账号未绑定公司")
    if core_role != CORE_ROLE_EMPLOYEE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="公司管理员只能创建和管理普通员工")
    if tenant and tenant.id != own_tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司员工")
    return own_tenant


def _assert_create_role_allowed(access: AccessContext, core_role: str) -> None:
    if access.is_platform_admin:
        if core_role != CORE_ROLE_COMPANY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="平台管理员只负责创建公司管理员")
        return
    if access.is_company_admin:
        if core_role != CORE_ROLE_EMPLOYEE:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="公司管理员只负责创建普通员工")
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权创建用户")


def _tenant_view(user: User) -> tuple[str | None, str | None]:
    row = next((item for item in user.tenant_roles if item.tenant), None)
    if row is not None:
        return row.tenant.code, row.tenant.name
    tenant_scope = next((item for item in user.data_scopes if item.scope_type == "tenant"), None)
    if tenant_scope is not None:
        return tenant_scope.scope_value, tenant_scope.scope_name
    return None, None


def _user_tenant_codes(db: Session, user: User) -> set[str]:
    codes = {item.tenant.code for item in user.tenant_roles if item.tenant and item.tenant.code}
    if codes:
        return codes

    result: set[str] = set()
    for item in user.data_scopes:
        if item.scope_type == "tenant":
            result.add(item.scope_value)
        elif item.scope_type == "site":
            site = db.scalar(select(Site).where(Site.code == item.scope_value))
            if site is not None:
                target = get_tenant_for_site(db, site.id)
                if target is not None:
                    result.add(target.code)
        elif item.scope_type == "device_group":
            device_group = db.scalar(select(DeviceGroup).where(DeviceGroup.code == item.scope_value))
            if device_group is not None:
                tenant = db.get(Tenant, device_group.tenant_id)
                if tenant is not None:
                    result.add(tenant.code)
        elif item.scope_type == "all":
            result.add("*")
    return result


def _assert_manageable_user(db: Session, access: AccessContext, user: User) -> None:
    target_core_role = get_user_core_role([role.name for role in user.roles])
    target_tenant_codes = _user_tenant_codes(db, user)
    if access.is_platform_admin:
        if target_core_role != CORE_ROLE_COMPANY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="平台管理员只能管理公司管理员")
        return
    if access.is_company_admin:
        if target_core_role != CORE_ROLE_EMPLOYEE:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="公司管理员只能管理普通员工")
        if not target_tenant_codes or not target_tenant_codes.issubset(access.tenant_codes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司员工")
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权管理该用户")


def _normalize_permission_keys(core_role: str, template_key: str | None, permission_keys: list[str]) -> list[str]:
    if core_role == CORE_ROLE_PLATFORM:
        return []

    merged = set(get_default_permissions_for_core_role(core_role))
    if core_role == CORE_ROLE_EMPLOYEE and template_key:
        try:
            merged.update(resolve_template_permissions(template_key))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        merged.update(normalize_assignable_permissions(permission_keys))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return sorted(merged)


def _site_belongs_tenant(db: Session, site_code: str, tenant_id: int) -> Site:
    site = db.scalar(select(Site).where(Site.code == site_code))
    if site is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"站点不存在：{site_code}")
    tenant = get_tenant_for_site(db, site.id)
    if tenant is None or tenant.id != tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"站点不属于当前公司：{site_code}")
    return site


def _device_group_belongs_tenant(db: Session, device_group_code: str, tenant_id: int) -> DeviceGroup:
    device_group = db.scalar(select(DeviceGroup).where(DeviceGroup.code == device_group_code))
    if device_group is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"设备组不存在：{device_group_code}")
    if device_group.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"设备组不属于当前公司：{device_group_code}")
    return device_group


def _normalize_data_scopes(
    db: Session,
    *,
    core_role: str,
    tenant: Tenant | None,
    payload_scopes: list[UserDataScopeAssign],
) -> list[UserDataScopeView]:
    if core_role == CORE_ROLE_PLATFORM:
        return [UserDataScopeView(scope_type="all", scope_value="*", scope_name="全部公司")]
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少所属公司")
    if core_role == CORE_ROLE_COMPANY:
        return [UserDataScopeView(scope_type="tenant", scope_value=tenant.code, scope_name=tenant.name)]

    normalized: dict[tuple[str, str], UserDataScopeView] = {}
    for item in payload_scopes:
        scope_type = str(item.scope_type or "").strip().lower()
        scope_value = str(item.scope_value or "").strip()
        if scope_type not in {"tenant", "site", "device_group"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持公司、站点、设备组数据范围")
        if not scope_value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据范围不能为空")
        if scope_type == "tenant":
            if scope_value != tenant.code:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="员工只能绑定所属公司范围")
            normalized[(scope_type, tenant.code)] = UserDataScopeView(
                scope_type="tenant",
                scope_value=tenant.code,
                scope_name=tenant.name,
            )
            continue
        if scope_type == "site":
            site = _site_belongs_tenant(db, scope_value, tenant.id)
            normalized[(scope_type, site.code)] = UserDataScopeView(
                scope_type="site",
                scope_value=site.code,
                scope_name=site.name,
            )
            continue
        device_group = _device_group_belongs_tenant(db, scope_value, tenant.id)
        normalized[(scope_type, device_group.code)] = UserDataScopeView(
            scope_type="device_group",
            scope_value=device_group.code,
            scope_name=device_group.name,
        )

    if not normalized:
        normalized[("tenant", tenant.code)] = UserDataScopeView(
            scope_type="tenant",
            scope_value=tenant.code,
            scope_name=tenant.name,
        )
    return sorted(normalized.values(), key=lambda item: (item.scope_type, item.scope_value))


def _sync_user_data_scopes(db: Session, user: User, scopes: list[UserDataScopeView]) -> None:
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


def _sync_user_roles(
    db: Session,
    *,
    user: User,
    core_role_role: Role,
    permission_role: Role | None,
    tenant: Tenant | None,
) -> None:
    roles = [core_role_role]
    if permission_role is not None:
        roles.append(permission_role)
    user.roles = roles
    user.tenant_roles.clear()
    db.flush()
    if tenant is None:
        return
    db.add(
        UserTenantRole(
            user_id=user.id,
            role_id=core_role_role.id,
            tenant_id=tenant.id,
            scope_level="tenant",
        )
    )


def _permission_role_for_user(user: User) -> Role | None:
    return next((role for role in user.roles if role.name == _permission_role_name(user.id)), None)


def _enabled_status_for_user(user: User, enabled: bool) -> str:
    if not enabled:
        return USER_STATUS_DISABLED
    if user.phone_verified_at or user.activated_at:
        return USER_STATUS_ACTIVE
    return USER_STATUS_PENDING


def _assert_unique_phone(
    db: Session,
    *,
    phone_country_code: str,
    phone: str,
    exclude_user_id: int | None = None,
) -> None:
    query = select(User).where(User.phone_country_code == phone_country_code, User.phone == phone)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    exists = db.scalar(query)
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="手机号已存在")


def _assert_unique_username(db: Session, *, username: str, exclude_user_id: int | None = None) -> None:
    query = select(User).where(User.username == username)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    exists = db.scalar(query)
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")


def _to_response(user: User) -> UserResponse:
    core_role = get_user_core_role([role.name for role in user.roles])
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
    expanded_permissions = {key for role in user.roles for key in get_role_permissions(role)}
    tenant_code, tenant_name = _tenant_view(user)
    return UserResponse(
        id=user.id,
        username=user.username,
        phone_country_code=user.phone_country_code,
        phone=user.phone,
        full_name=user.full_name,
        is_active=user.is_active,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        core_role=core_role,
        roles=[core_role],
        permissions=simplify_permissions(expanded_permissions),
        tenant_roles=tenant_roles,
        data_scopes=[
            UserDataScopeView(
                scope_type=item.scope_type,
                scope_value=item.scope_value,
                scope_name=item.scope_name,
            )
            for item in sorted(user.data_scopes, key=lambda x: (x.scope_type, x.scope_value, x.id))
        ],
        tenant_code=tenant_code,
        tenant_name=tenant_name,
        template_key=match_template_key(expanded_permissions),
    )


def _core_role_response(core_role: str) -> RoleDefResponse:
    return RoleDefResponse(
        id=0,
        name=core_role,
        description=CORE_ROLE_LABELS[core_role],
        is_builtin=True,
        permissions=sorted(get_default_permissions_for_core_role(core_role)),
    )


@router.get("/meta", response_model=UserMetaResponse)
def get_user_meta(_=Depends(require_user_manager)):
    return UserMetaResponse(
        permission_options=get_permission_options(),
        scope_type_options=get_scope_type_options(),
        core_role_options=get_core_role_options(),
        permission_templates=get_permission_templates(),
    )


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_user_manager),
    access: AccessContext = Depends(get_access_context),
):
    users = list(db.scalars(select(User).order_by(User.id.desc())).all())
    result: list[UserResponse] = []
    for item in users:
        core_role = get_user_core_role([role.name for role in item.roles])
        if access.is_platform_admin:
            result.append(_to_response(item))
            continue
        if core_role != CORE_ROLE_EMPLOYEE:
            continue
        tenant_codes = _user_tenant_codes(db, item)
        if tenant_codes and tenant_codes.issubset(access.tenant_codes):
            result.append(_to_response(item))
    return result


@router.get("/roles", response_model=list[str])
def list_roles(_=Depends(require_user_manager)):
    return [CORE_ROLE_PLATFORM, CORE_ROLE_COMPANY, CORE_ROLE_EMPLOYEE]


@router.get("/role-defs", response_model=list[RoleDefResponse])
def list_role_defs(_=Depends(require_user_manager)):
    return [_core_role_response(item.key) for item in CORE_ROLE_DEFINITIONS]


@router.post("/role-defs", response_model=RoleDefResponse)
def create_role_def(_payload: RoleDefCreate, _=Depends(require_user_manager)):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前版本不支持自定义角色，请使用核心角色和权限模板")


@router.put("/role-defs/{role_id}", response_model=RoleDefResponse)
def update_role_def(role_id: int, _payload: RoleDefUpdate, _=Depends(require_user_manager)):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前版本不支持修改角色定义")


@router.delete("/role-defs/{role_id}", response_model=dict[str, str])
def delete_role_def(role_id: int, _=Depends(require_user_manager)):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前版本不支持删除角色定义")


@router.post("", response_model=UserResponse)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
    access: AccessContext = Depends(get_access_context),
):
    phone_country_code, phone = _normalize_phone_input(payload.phone_country_code, payload.phone)
    username = _normalize_username(payload.username, fallback_phone=phone)
    password = _normalize_password(payload.password, required=False) or secrets.token_urlsafe(16)
    _assert_unique_username(db, username=username)
    _assert_unique_phone(db, phone_country_code=phone_country_code, phone=phone)

    core_role = _normalize_core_role(payload.core_role, payload.role_names)
    _assert_create_role_allowed(access, core_role)
    tenant = _resolve_target_tenant(db, access, core_role=core_role, tenant_code=payload.tenant_code)
    permission_keys = _normalize_permission_keys(core_role, payload.template_key, payload.permission_keys)
    core_role_role = _resolve_core_role(db, core_role)

    item = User(
        username=username,
        password_hash=get_password_hash(password),
        phone_country_code=phone_country_code,
        phone=phone,
        full_name=(payload.full_name or "").strip() or None,
        status=USER_STATUS_PENDING if core_role != CORE_ROLE_PLATFORM else USER_STATUS_ACTIVE,
        is_active=True,
    )
    db.add(item)
    db.flush()
    permission_role = None
    if core_role != CORE_ROLE_PLATFORM:
        permission_role = _resolve_permission_role(db, item.id)
        _sync_role_permissions(db, permission_role, permission_keys)
    _sync_user_roles(db, user=item, core_role_role=core_role_role, permission_role=permission_role, tenant=tenant)
    _sync_user_data_scopes(
        db,
        item,
        _normalize_data_scopes(db, core_role=core_role, tenant=tenant, payload_scopes=payload.data_scopes),
    )
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id if tenant else None,
        action="user.create",
        target_type="user",
        target_id=str(item.id),
        content=f"创建用户 {item.username}，核心角色 {core_role}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.post("/batch", response_model=UserBatchCreateResponse)
def batch_create_users(
    payload: UserBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
    access: AccessContext = Depends(get_access_context),
):
    if not access.is_company_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅公司管理员可批量创建员工")
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少提供一条用户记录")

    core_role = _normalize_core_role(payload.core_role, payload.role_names or [CORE_ROLE_EMPLOYEE])
    if core_role != CORE_ROLE_EMPLOYEE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="批量创建仅支持普通员工")
    tenant = _resolve_target_tenant(db, access, core_role=core_role, tenant_code=payload.tenant_code)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少所属公司")

    permission_keys = _normalize_permission_keys(core_role, payload.template_key, payload.permission_keys)
    core_role_role = _resolve_core_role(db, core_role)
    default_scopes = _normalize_data_scopes(db, core_role=core_role, tenant=tenant, payload_scopes=payload.data_scopes)
    default_password = _normalize_password(payload.default_password, required=False)
    on_existing = str(payload.on_existing or "skip").strip().lower()
    if on_existing not in {"skip", "update_name", "reset_password"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的重复账号处理策略")

    created_items: list[dict] = []
    updated_items: list[dict] = []
    skipped_items: list[dict] = []
    failed_items: list[dict] = []

    for row in payload.items:
        row_identity = str(row.phone or row.username or "").strip()
        try:
            phone_country_code, phone = _normalize_phone_input(row.phone_country_code, row.phone)
            username = _normalize_username(row.username, fallback_phone=phone)
            password = _normalize_password(row.password or default_password, required=False) or secrets.token_urlsafe(16)
            exists = db.scalar(
                select(User).where(User.phone_country_code == phone_country_code, User.phone == phone)
            )
            if exists is not None:
                _assert_manageable_user(db, access, exists)
                if on_existing == "skip":
                    skipped_items.append({"username": exists.username, "message": "手机号已存在，已跳过"})
                    continue
                exists.full_name = (row.full_name or "").strip() or None
                if on_existing == "reset_password":
                    exists.password_hash = get_password_hash(password)
                    updated_items.append({"username": exists.username, "message": "已更新姓名并重置内部密码"})
                else:
                    updated_items.append({"username": exists.username, "message": "已更新姓名"})
                continue

            _assert_unique_username(db, username=username)
            item = User(
                username=username,
                password_hash=get_password_hash(password),
                phone_country_code=phone_country_code,
                phone=phone,
                full_name=(row.full_name or "").strip() or None,
                status=USER_STATUS_PENDING,
                is_active=True,
            )
            db.add(item)
            db.flush()
            permission_role = _resolve_permission_role(db, item.id)
            _sync_role_permissions(db, permission_role, permission_keys)
            _sync_user_roles(
                db,
                user=item,
                core_role_role=core_role_role,
                permission_role=permission_role,
                tenant=tenant,
            )
            _sync_user_data_scopes(db, item, default_scopes)
            created_items.append({"username": username, "message": "创建成功"})
        except HTTPException as exc:
            failed_items.append({"username": row_identity, "message": str(exc.detail)})

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="user.batch_create",
        target_type="user_batch",
        target_id=tenant.code,
        content=(
            f"批量创建员工：成功 {len(created_items)} 条，"
            f"更新 {len(updated_items)} 条，跳过 {len(skipped_items)} 条，失败 {len(failed_items)} 条"
        ),
    )
    db.commit()
    return UserBatchCreateResponse(
        created_count=len(created_items),
        updated_count=len(updated_items),
        skipped_count=len(skipped_items),
        failed_count=len(failed_items),
        usernames=[item["username"] for item in created_items],
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
    current_user: User = Depends(require_user_manager),
    access: AccessContext = Depends(get_access_context),
):
    item = db.get(User, user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    _assert_manageable_user(db, access, item)

    phone_country_code, phone = _normalize_phone_input(payload.phone_country_code, payload.phone)
    username = _normalize_username(payload.username, fallback_phone=phone)
    _assert_unique_username(db, username=username, exclude_user_id=user_id)
    _assert_unique_phone(db, phone_country_code=phone_country_code, phone=phone, exclude_user_id=user_id)
    if not payload.is_active and current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用当前登录用户")

    current_core_role = get_user_core_role([role.name for role in item.roles])
    core_role = _normalize_core_role(payload.core_role or current_core_role, payload.role_names or [current_core_role])
    if core_role != current_core_role:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前版本不支持编辑时切换核心角色")

    tenant = _resolve_target_tenant(db, access, core_role=core_role, tenant_code=payload.tenant_code or _tenant_view(item)[0])
    permission_keys = _normalize_permission_keys(core_role, payload.template_key, payload.permission_keys)
    core_role_role = _resolve_core_role(db, core_role)

    item.username = username
    item.phone_country_code = phone_country_code
    item.phone = phone
    item.full_name = (payload.full_name or "").strip() or None
    item.is_active = payload.is_active
    item.status = _enabled_status_for_user(item, payload.is_active)
    if item.status != USER_STATUS_DISABLED:
        item.locked_until = None
        item.login_fail_count = 0
    password = _normalize_password(payload.password, required=False)
    if password:
        item.password_hash = get_password_hash(password)

    permission_role = None
    if core_role != CORE_ROLE_PLATFORM:
        permission_role = _permission_role_for_user(item) or _resolve_permission_role(db, item.id)
        _sync_role_permissions(db, permission_role, permission_keys)
    _sync_user_roles(
        db,
        user=item,
        core_role_role=core_role_role,
        permission_role=permission_role,
        tenant=tenant,
    )
    _sync_user_data_scopes(
        db,
        item,
        _normalize_data_scopes(db, core_role=core_role, tenant=tenant, payload_scopes=payload.data_scopes),
    )
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id if tenant else None,
        action="user.update",
        target_type="user",
        target_id=str(item.id),
        content=f"更新用户 {item.username}，核心角色 {core_role}，状态 {item.status}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.delete("/{user_id}", response_model=dict[str, str])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
    access: AccessContext = Depends(get_access_context),
):
    item = db.get(User, user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前登录用户")
    _assert_manageable_user(db, access, item)

    tenant_code, _ = _tenant_view(item)
    tenant = _tenant_from_code(db, tenant_code)
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
