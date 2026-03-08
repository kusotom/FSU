from pydantic import BaseModel


class ProjectResponse(BaseModel):
    id: int
    tenant_code: str
    code: str
    name: str
    status: str


class ProjectCreate(BaseModel):
    code: str
    name: str


class ProjectUpdate(BaseModel):
    name: str
    status: str = "active"
