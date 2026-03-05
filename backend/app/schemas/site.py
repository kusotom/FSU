from datetime import datetime

from pydantic import BaseModel


class SiteCreate(BaseModel):
    code: str
    name: str
    region: str | None = None
    tenant_code: str | None = None


class SiteUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    region: str | None = None
    tenant_code: str | None = None
    is_active: bool | None = None


class SiteResponse(BaseModel):
    id: int
    code: str
    name: str
    region: str | None
    tenant_code: str | None = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
