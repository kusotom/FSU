from pydantic import BaseModel, Field


class CustomScopeSetCreate(BaseModel):
    name: str
    resource_type: str = "site"
    resource_ids: list[int] = Field(default_factory=list)


class CustomScopeSetUpdate(BaseModel):
    name: str
    resource_ids: list[int] = Field(default_factory=list)


class CustomScopeSetResponse(BaseModel):
    id: int
    tenant_code: str
    name: str
    resource_type: str
    resource_ids: list[int] = Field(default_factory=list)
    item_count: int = 0
