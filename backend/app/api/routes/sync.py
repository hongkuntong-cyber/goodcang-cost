"""同步相关 API 路由：手动触发同步、查看同步日志。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import SyncLog
from app.tasks.sync_tasks import run_sync_now

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/run")
async def trigger_sync():
    """手动触发一次全量同步。"""
    result = await run_sync_now()
    return {"status": "success", "result": result}


@router.get("/logs")
def list_logs(limit: int = 20, db: Session = Depends(get_db)):
    """最近 N 条同步日志。"""
    rows = db.scalars(
        select(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit)
    ).all()
    return {"logs": [
        {
            "task_name": r.task_name, "endpoint": r.endpoint, "status": r.status,
            "records_affected": r.records_affected, "message": r.message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        } for r in rows
    ]}