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


class UserBatchItem(BaseModel):
    username: str
    full_name: str | None = None
    password: str | None = None


class UserBatchCreate(BaseModel):
    items: list[UserBatchItem] = Field(default_factory=list)
    default_password: str | None = None
    on_existing: str = "skip"
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


class UserBatchCreateResponse(BaseModel):
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    usernames: list[str] = Field(default_factory=list)
    created_items: list[dict] = Field(default_factory=list)
    updated_items: list[dict] = Field(default_factory=list)
    skipped_items: list[dict] = Field(default_factory=list)
    failed_items: list[dict] = Field(default_factory=list)
