from datetime import datetime

from pydantic import BaseModel


class OperationLogResponse(BaseModel):
    id: int
    operator_id: int | None = None
    operator_name: str | None = None
    tenant_code: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    content: str
    created_at: datetime
