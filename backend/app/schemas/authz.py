from pydantic import BaseModel, Field

from app.schemas.user import UserDataScopeAssign, UserDataScopeView


class RolePermissionBindRequest(BaseModel):
    permission_keys: list[str] = Field(default_factory=list)


class RolePermissionBindResponse(BaseModel):
    role_name: str
    permissions: list[str] = Field(default_factory=list)


class UserScopeBindRequest(BaseModel):
    data_scopes: list[UserDataScopeAssign] = Field(default_factory=list)


class UserScopeBindResponse(BaseModel):
    user_id: int
    data_scopes: list[UserDataScopeView] = Field(default_factory=list)
