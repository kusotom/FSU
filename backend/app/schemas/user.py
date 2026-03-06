from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tenant import UserTenantRoleAssign, UserTenantRoleView


class UserDataScopeAssign(BaseModel):
    scope_type: str
    scope_value: str


class UserDataScopeView(BaseModel):
    scope_type: str
    scope_value: str
    scope_name: str | None = None


class PermissionOption(BaseModel):
    key: str
    label: str
    description: str


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    role_names: list[str] = Field(default_factory=lambda: ["operator"])
    tenant_roles: list[UserTenantRoleAssign] = Field(default_factory=list)
    data_scopes: list[UserDataScopeAssign] = Field(default_factory=list)


class UserUpdate(BaseModel):
    username: str
    password: str | None = None
    full_name: str | None = None
    is_active: bool = True
    role_names: list[str] = Field(default_factory=list)
    tenant_roles: list[UserTenantRoleAssign] = Field(default_factory=list)
    data_scopes: list[UserDataScopeAssign] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str | None
    is_active: bool
    created_at: datetime
    roles: list[str]
    permissions: list[str] = Field(default_factory=list)
    tenant_roles: list[UserTenantRoleView] = Field(default_factory=list)
    data_scopes: list[UserDataScopeView] = Field(default_factory=list)


class RoleDefCreate(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleDefUpdate(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleDefResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_builtin: bool = False
    permissions: list[str] = Field(default_factory=list)


class UserMetaResponse(BaseModel):
    permission_options: list[PermissionOption] = Field(default_factory=list)
    scope_type_options: list[PermissionOption] = Field(default_factory=list)
