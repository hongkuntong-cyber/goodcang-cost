"""数据库连接：SQLAlchemy 2.x engine + Session。

使用方式：
- engine：全局共享，供 Alembic 迁移和 FastAPI 依赖注入
- SessionLocal：会话工厂
- get_db：FastAPI 路由依赖，每次请求自动开关 Session
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的统一基类。"""


# ---- engine：连接池 + 预编译（SQLAlchemy 2.x 风格）----
_settings = get_settings()

# 连接池参数仅在 PostgreSQL 下有效；SQLite（测试）跳过
_pool_args: dict = {}
if _settings.database_url.startswith("postgresql"):
    _pool_args = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}

engine = create_engine(
    _settings.database_url,
    future=True,
    **_pool_args,
)

# ---- SessionLocal：会话工厂 ----
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供请求级 Session，结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()