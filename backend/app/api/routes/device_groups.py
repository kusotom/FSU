from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.device_group import DeviceGroup
from app.models.project import Project
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding
from app.models.user import UserDataScope
from app.schemas.device_group import DeviceGroupCreate, DeviceGroupResponse, DeviceGroupUpdate
from app.services.access_control import AccessContext
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/device-groups", tags=["device-groups"])


def _assert_tenant_allowed(access: AccessContext, tenant_id: int) -> None:
    if access.can_global_read:
        return
    if tenant_id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司设备组")


def _get_tenant_by_code(db: Session, tenant_code: str) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    return tenant


def _validate_resource_belongs_tenant(db: Session, tenant_id: int, project_id: int | None, site_id: int | None) -> None:
    if project_id is not None:
        project = db.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        if project is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目不属于当前公司")
    if site_id is not None:
        site = db.get(Site, site_id)
        if site is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="站点不存在")
        binding = db.scalar(
            select(TenantSiteBinding).where(
                TenantSiteBinding.site_id == site_id,
                TenantSiteBinding.tenant_id == tenant_id,
            )
        )
        if binding is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="站点不属于当前公司")


def _to_response(device_group: DeviceGroup, tenant_code: str) -> DeviceGroupResponse:
    return DeviceGroupResponse(
        id=device_group.id,
        tenant_code=tenant_code,
        project_id=device_group.project_id,
        site_id=device_group.site_id,
        code=device_group.code,
        name=device_group.name,
    )


@router.get("", response_model=list[DeviceGroupResponse])
def list_device_groups(
    tenant_code: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("site.view")),
):
    stmt = select(DeviceGroup, Tenant.code.label("tenant_code")).join(Tenant, Tenant.id == DeviceGroup.tenant_id)
    if tenant_code:
        stmt = stmt.where(Tenant.code == tenant_code)
    if not access.can_global_read:
        if not access.tenant_ids:
            return []
        stmt = stmt.where(DeviceGroup.tenant_id.in_(access.tenant_ids))
    rows = db.execute(stmt.order_by(DeviceGroup.id.asc())).all()
    return [_to_response(device_group, current_tenant_code) for device_group, current_tenant_code in rows]


@router.post("", response_model=DeviceGroupResponse)
def create_device_group(
    tenant_code: str,
    payload: DeviceGroupCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    access: AccessContext = Depends(permission_required("site.update")),
):
    tenant = _get_tenant_by_code(db, tenant_code)
    _assert_tenant_allowed(access, tenant.id)
    _validate_resource_belongs_tenant(db, tenant.id, payload.project_id, payload.site_id)

    code = (payload.code or "").strip().upper()
    name = (payload.name or "").strip()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="设备组编码不能为空")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="设备组名称不能为空")

    exists = db.scalar(select(DeviceGroup).where(DeviceGroup.tenant_id == tenant.id, DeviceGroup.code == code))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="设备组编码已存在")

    device_group = DeviceGroup(
        tenant_id=tenant.id,
        project_id=payload.project_id,
        site_id=payload.site_id,
        code=code,
        name=name,
    )
    db.add(device_group)
    db.flush()
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="device_group.create",
        target_type="device_group",
        target_id=code,
        content=f"创建设备组 {name}（{code}）",
    )
    db.commit()
    db.refresh(device_group)
    return _to_response(device_group, tenant.code)


@router.put("/{device_group_id}", response_model=DeviceGroupResponse)
def update_device_group(
    device_group_id: int,
    tenant_code: str,
    payload: DeviceGroupUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    access: AccessContext = Depends(permission_required("site.update")),
):
    device_group = db.get(DeviceGroup, device_group_id)
    if device_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备组不存在")

    tenant = _get_tenant_by_code(db, tenant_code)
    if device_group.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司与设备组不匹配")
    _assert_tenant_allowed(access, tenant.id)
    _validate_resource_belongs_tenant(db, tenant.id, payload.project_id, payload.site_id)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="设备组名称不能为空")

    device_group.name = name
    device_group.project_id = payload.project_id
    device_group.site_id = payload.site_id
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="device_group.update",
        target_type="device_group",
        target_id=device_group.code,
        content=f"更新设备组 {device_group.name}（{device_group.code}）",
    )
    db.commit()
    db.refresh(device_group)
    return _to_response(device_group, tenant.code)


@router.delete("/{device_group_id}")
def delete_device_group(
    device_group_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    access: AccessContext = Depends(permission_required("site.update")),
):
    device_group = db.get(DeviceGroup, device_group_id)
    if device_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备组不存在")

    tenant = _get_tenant_by_code(db, tenant_code)
    if device_group.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司与设备组不匹配")
    _assert_tenant_allowed(access, tenant.id)

    has_user_scope = db.scalar(
        select(UserDataScope.id).where(
            UserDataScope.scope_type == "device_group",
            UserDataScope.scope_value == device_group.code,
        ).limit(1)
    )
    if has_user_scope is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="设备组已被用户数据范围引用，不能删除")

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="device_group.delete",
        target_type="device_group",
        target_id=device_group.code,
        content=f"删除设备组 {device_group.name}（{device_group.code}）",
    )
    db.delete(device_group)
    db.commit()
    return {"message": "设备组已删除"}
