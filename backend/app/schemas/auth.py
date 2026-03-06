from pydantic import BaseModel, Field

from app.schemas.tenant import UserTenantRoleView
from app.schemas.user import UserDataScopeView


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRoleBindingResponse(BaseModel):
    role_name: str
    permissions: list[str] = Field(default_factory=list)
    tenant_bindings: list[dict] = Field(default_factory=list)
    scopes: list[dict] = Field(default_factory=list)


class UserMeResponse(BaseModel):
    id: int
    username: str
    full_name: str | None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    scopes: list[UserDataScopeView] = Field(default_factory=list)
    role_bindings: list[UserRoleBindingResponse] = Field(default_factory=list)
    tenant_codes: list[str] = Field(default_factory=list)
    tenant_roles: list[UserTenantRoleView] = Field(default_factory=list)
