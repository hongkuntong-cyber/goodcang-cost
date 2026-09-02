"""定时同步任务调度（APScheduler）。

默认每日 02:00 全量同步（可用 SYNC_ENABLED / SYNC_CRON 配置）。
也暴露一个可直接调用的 run_sync_now() 供手动触发 / 测试。
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.connectors.goodcang import GoodCangClient, GoodCangEndpoints
from app.services.sync_service import SyncService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_sync_now() -> dict[str, int]:
    """手动触发一次全量同步。"""
    async with GoodCangClient() as client:
        endpoints = GoodCangEndpoints(client)
        with SessionLocal() as db:
            service = SyncService(db, client, endpoints)
            return await service.sync_all()


def start_scheduler() -> AsyncIOScheduler:
    """启动调度器；由 FastAPI startup 调用。"""
    global _scheduler
    settings = get_settings()
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    if settings.sync_enabled:
        cron_parts = settings.sync_cron.split()
        _scheduler.add_job(
            lambda: asyncio.create_task(run_sync_now()),
            CronTrigger(
                minute=cron_parts[0], hour=cron_parts[1],
                day=cron_parts[2], month=cron_parts[3], day_of_week=cron_parts[4],
            ),
            id="goodcang_daily_sync",
            name="每日全量同步",
        )
        logger.info("scheduler started with cron=%s", settings.sync_cron)
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None