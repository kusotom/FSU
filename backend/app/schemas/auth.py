from pydantic import BaseModel, Field

from app.schemas.tenant import UserTenantRoleView


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMeResponse(BaseModel):
    id: int
    username: str
    full_name: str | None
    roles: list[str]
    is_admin: bool = False
    tenant_codes: list[str] = Field(default_factory=list)
    is_hq_noc: bool = False
    tenant_roles: list[UserTenantRoleView] = Field(default_factory=list)
