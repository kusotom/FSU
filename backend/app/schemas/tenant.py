from datetime import datetime

from pydantic import BaseModel


class TenantResponse(BaseModel):
    id: int
    code: str
    name: str
    tenant_type: str
    parent_code: str | None = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserTenantRoleAssign(BaseModel):
    tenant_code: str
    role_name: str


class UserTenantRoleView(BaseModel):
    tenant_code: str
    tenant_name: str
    tenant_type: str
    role_name: str
    scope_level: str
