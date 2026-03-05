import asyncio
import logging

from app.api.routes.ingest import run_system_rule_sweep_once
from app.core.config import settings

logger = logging.getLogger(__name__)


async def system_rule_worker_loop():
    interval = max(settings.system_rule_eval_interval_seconds, 5)
    while True:
        try:
            await run_system_rule_sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("system rule sweep failed")
        await asyncio.sleep(interval)
