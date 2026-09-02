"""pytest fixtures：内存 SQLite + 表创建，方便单元测试无需 PostgreSQL。

后续 Step 7 可以补一个 pg 容器跑迁移的 integration fixture。
"""
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
import app.models  # noqa: F401  -- 注册所有表


@pytest.fixture()
def engine():
    """每个测试一个内存 SQLite 引擎。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Generator[Session, None, None]:
    """与 engine 绑定的 Session。"""
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()