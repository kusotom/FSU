from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tenant import UserTenantRoleAssign, UserTenantRoleView


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    role_names: list[str] = Field(default_factory=lambda: ["operator"])
    tenant_roles: list[UserTenantRoleAssign] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str | None
    is_active: bool
    created_at: datetime
    roles: list[str]
    tenant_roles: list[UserTenantRoleView] = Field(default_factory=list)


class RoleDefCreate(BaseModel):
    name: str
    description: str | None = None


class RoleDefUpdate(BaseModel):
    name: str
    description: str | None = None


class RoleDefResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_builtin: bool = False
