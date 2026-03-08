from pydantic import BaseModel


class DeviceGroupResponse(BaseModel):
    id: int
    tenant_code: str
    project_id: int | None = None
    site_id: int | None = None
    code: str
    name: str


class DeviceGroupCreate(BaseModel):
    code: str
    name: str
    project_id: int | None = None
    site_id: int | None = None


class DeviceGroupUpdate(BaseModel):
    name: str
    project_id: int | None = None
    site_id: int | None = None
