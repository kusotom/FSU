import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.tenant import Tenant, UserTenantRole
from app.models.user import Role, User, user_roles
from app.schemas.tenant import UserTenantRoleView
from app.schemas.user import (
    RoleDefCreate,
    RoleDefResponse,
    RoleDefUpdate,
    UserCreate,
    UserResponse,
)
from app.services.access_control import HQ_TENANT_CODE

router = APIRouter(prefix="/users", tags=["users"])
BUILTIN_ROLE_NAMES = {"admin", "operator", "hq_noc", "sub_noc"}
GLOBAL_ROLE_NAMES = {"admin", "hq_noc"}


def _normalize_role_name(value: str) -> str:
    name = value.strip().lower()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色名称不能为空")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色名称仅支持小写字母、数字、下划线，且以字母开头（2-64位）",
        )
    return name


def _to_response(user: User) -> UserResponse:
    tenant_roles = [
        UserTenantRoleView(
            tenant_code=item.tenant.code,
            tenant_name=item.tenant.name,
            tenant_type=item.tenant.tenant_type,
            role_name=item.role.name,
            scope_level=item.scope_level,
        )
        for item in sorted(
            user.tenant_roles,
            key=lambda x: (x.tenant.code, x.role.name, x.id),
        )
    ]
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        roles=sorted({r.name for r in user.roles}),
        tenant_roles=tenant_roles,
    )


def _ensure_user_tenant_role(db: Session, *, user: User, role: Role, tenant: Tenant):
    exists = db.scalar(
        select(UserTenantRole).where(
            UserTenantRole.user_id == user.id,
            UserTenantRole.role_id == role.id,
            UserTenantRole.tenant_id == tenant.id,
        )
    )
    if exists is not None:
        return
    db.add(
        UserTenantRole(
            user_id=user.id,
            role_id=role.id,
            tenant_id=tenant.id,
            scope_level="tenant",
        )
    )


def _validate_tenant_role_assignment(*, role_name: str, tenant: Tenant):
    if role_name in {"admin", "hq_noc"} and tenant.code != HQ_TENANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"角色 {role_name} 仅允许绑定到 {HQ_TENANT_CODE}",
        )
    if role_name == "sub_noc" and tenant.code == HQ_TENANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色 sub_noc 不能绑定到总部租户",
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
    return [
        RoleDefResponse(
            id=item.id,
            name=item.name,
            description=item.description,
            is_builtin=item.name in BUILTIN_ROLE_NAMES,
        )
        for item in rows
    ]


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

    item = Role(name=role_name, description=(payload.description or "").strip() or None)
    db.add(item)
    db.commit()
    db.refresh(item)
    return RoleDefResponse(
        id=item.id,
        name=item.name,
        description=item.description,
        is_builtin=item.name in BUILTIN_ROLE_NAMES,
    )


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内置角色不允许改名")
    if new_name != item.name:
        exists = db.scalar(select(Role).where(Role.name == new_name))
        if exists is not None and exists.id != item.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="角色名称已存在")
        item.name = new_name
    item.description = (payload.description or "").strip() or None
    db.commit()
    db.refresh(item)
    return RoleDefResponse(
        id=item.id,
        name=item.name,
        description=item.description,
        is_builtin=item.name in BUILTIN_ROLE_NAMES,
    )


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
        db.scalar(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role_id)
        )
        or 0
    )
    tenant_role_ref_count = int(
        db.scalar(
            select(func.count(UserTenantRole.id)).where(UserTenantRole.role_id == role_id)
        )
        or 0
    )
    if user_role_ref_count > 0 or tenant_role_ref_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "角色已被引用，无法删除："
                f"用户角色关联={user_role_ref_count}，"
                f"租户角色关联={tenant_role_ref_count}"
            ),
        )

    db.delete(item)
    db.commit()
    return {"message": "角色已删除"}


@router.post("", response_model=UserResponse)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="\u7528\u6237\u540d\u5df2\u5b58\u5728")

    role_names = sorted(
        {
            *{name.strip() for name in payload.role_names if name.strip()},
            *{item.role_name.strip() for item in payload.tenant_roles if item.role_name.strip()},
        }
    )
    if not role_names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u8bf7\u81f3\u5c11\u6307\u5b9a\u4e00\u4e2a\u89d2\u8272")

    roles = list(db.scalars(select(Role).where(Role.name.in_(role_names))).all())
    role_map = {item.name: item for item in roles}
    if len(role_map) != len(role_names):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u89d2\u8272\u65e0\u6548")

    user = User(
        username=payload.username,
        password_hash=get_password_hash(payload.password),
        full_name=payload.full_name,
        is_active=True,
    )
    for role in roles:
        user.roles.append(role)
    db.add(user)
    db.flush()

    hq_tenant = db.scalar(select(Tenant).where(Tenant.code == HQ_TENANT_CODE))
    explicit_tenant_by_id: dict[int, Tenant] = {}
    assigned_role_names: set[str] = set()
    if payload.tenant_roles:
        for item in payload.tenant_roles:
            role = role_map.get(item.role_name)
            if role is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"租户角色必须属于 role_names: {item.role_name}",
                )
            tenant = db.scalar(select(Tenant).where(Tenant.code == item.tenant_code))
            if tenant is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"租户不存在: {item.tenant_code}",
                )
            _validate_tenant_role_assignment(role_name=role.name, tenant=tenant)
            _ensure_user_tenant_role(db, user=user, role=role, tenant=tenant)
            assigned_role_names.add(role.name)
            explicit_tenant_by_id[tenant.id] = tenant

    explicit_tenants = [explicit_tenant_by_id[k] for k in sorted(explicit_tenant_by_id.keys())]

    for role_name in role_names:
        if role_name in assigned_role_names:
            continue
        role = role_map[role_name]
        if role_name in GLOBAL_ROLE_NAMES:
            if hq_tenant is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少总部租户，无法绑定全局角色")
            _validate_tenant_role_assignment(role_name=role_name, tenant=hq_tenant)
            _ensure_user_tenant_role(db, user=user, role=role, tenant=hq_tenant)
            continue

        if not explicit_tenants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"角色 {role_name} 必须至少绑定一个租户",
            )
        for tenant in explicit_tenants:
            _validate_tenant_role_assignment(role_name=role_name, tenant=tenant)
            _ensure_user_tenant_role(db, user=user, role=role, tenant=tenant)

    db.commit()
    db.refresh(user)
    return _to_response(user)
