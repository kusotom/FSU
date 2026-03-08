from sqlalchemy.orm import Session

from app.models.operation_log import OperationLog


def write_operation_log(
    db: Session,
    *,
    action: str,
    target_type: str,
    content: str,
    operator_id: int | None = None,
    tenant_id: int | None = None,
    target_id: str | None = None,
):
    db.add(
        OperationLog(
            operator_id=operator_id,
            tenant_id=tenant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            content=content,
        )
    )
