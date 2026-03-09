from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.device_group import DeviceGroup
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import UserDataScope
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.access_control import AccessContext
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/projects", tags=["projects"])


def _assert_tenant_allowed(access: AccessContext, tenant_id: int) -> None:
    if access.can_global_read:
        return
    if tenant_id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司项目")


def _get_tenant_by_code(db: Session, tenant_code: str) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    return tenant


def _to_response(project: Project, tenant_code: str) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        tenant_code=tenant_code,
        code=project.code,
        name=project.name,
        status=project.status,
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    tenant_code: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("site.view")),
):
    stmt = select(Project, Tenant.code.label("tenant_code")).join(Tenant, Tenant.id == Project.tenant_id)
    if tenant_code:
        stmt = stmt.where(Tenant.code == tenant_code)
    if not access.can_global_read:
        if not access.tenant_ids:
            return []
        stmt = stmt.where(Project.tenant_id.in_(access.tenant_ids))
    rows = db.execute(stmt.order_by(Project.id.asc())).all()
    return [_to_response(project, current_tenant_code) for project, current_tenant_code in rows]


@router.post("", response_model=ProjectResponse)
def create_project(
    tenant_code: str,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    access: AccessContext = Depends(permission_required("site.update")),
):
    tenant = _get_tenant_by_code(db, tenant_code)
    _assert_tenant_allowed(access, tenant.id)

    code = (payload.code or "").strip().upper()
    name = (payload.name or "").strip()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目编码不能为空")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目名称不能为空")

    exists = db.scalar(select(Project).where(Project.tenant_id == tenant.id, Project.code == code))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目编码已存在")

    project = Project(tenant_id=tenant.id, code=code, name=name, status="active")
    db.add(project)
    db.flush()
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="project.create",
        target_type="project",
        target_id=code,
        content=f"创建项目 {name}（{code}）",
    )
    db.commit()
    db.refresh(project)
    return _to_response(project, tenant.code)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    tenant_code: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    access: AccessContext = Depends(permission_required("site.update")),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    tenant = _get_tenant_by_code(db, tenant_code)
    if project.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司与项目不匹配")
    _assert_tenant_allowed(access, tenant.id)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目名称不能为空")

    project.name = name
    project.status = (payload.status or "active").strip() or "active"
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="project.update",
        target_type="project",
        target_id=project.code,
        content=f"更新项目 {project.name}（{project.code}），状态={project.status}",
    )
    db.commit()
    db.refresh(project)
    return _to_response(project, tenant.code)


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    access: AccessContext = Depends(permission_required("site.update")),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    tenant = _get_tenant_by_code(db, tenant_code)
    if project.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司与项目不匹配")
    _assert_tenant_allowed(access, tenant.id)

    has_device_groups = db.scalar(select(DeviceGroup.id).where(DeviceGroup.project_id == project.id).limit(1))
    if has_device_groups is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目下存在设备组，不能删除")

    has_user_scope = db.scalar(
        select(UserDataScope.id).where(
            UserDataScope.scope_type == "project",
            UserDataScope.scope_value == project.code,
        ).limit(1)
    )
    if has_user_scope is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目已被用户数据范围引用，不能删除")

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="project.delete",
        target_type="project",
        target_id=project.code,
        content=f"删除项目 {project.name}（{project.code}）",
    )
    db.delete(project)
    db.commit()
    return {"message": "项目已删除"}
