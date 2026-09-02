"""应用配置：通过 pydantic-settings 从 .env / 环境变量读取。

设计原则：
- 绝不在代码中硬编码敏感信息（GoodCang AppToken/AppKey、数据库密码等）
- 所有可配置项集中在 Settings 单例，便于测试时通过 env 覆盖
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。所有字段都会从 .env 或环境变量读取。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用基础 ----
    app_name: str = Field(default="GoodCang Cost Intelligence", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")  # dev / uat / prod
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ---- 数据库 ----
    database_url: str = Field(
        default="postgresql+psycopg2://goodcang:goodcang@localhost:5432/goodcang_cost",
        alias="DATABASE_URL",
    )

    # ---- 谷仓 GoodCang Open API ----
    # 鉴权方式（2026-09-01 校准）：谷仓采用 HTTP Header 鉴权，每次请求需携带两个 header
    #   - app-token : AppToken（账号维度）
    #   - app-key   : AppKey（账号维度）
    # 接口方法统一为 POST + JSON body，业务接口路径前缀为 /public_open
    # 凭据在 GWC OMS 后台 → 我的 → 开发者信息 → 海外仓 获取
    goodcang_app_token: str = Field(default="", alias="GOODCANG_APP_TOKEN")
    goodcang_app_key: str = Field(default="", alias="GOODCANG_APP_KEY")
    goodcang_base_url: str = Field(
        default="https://oms.goodcang.net", alias="GOODCANG_BASE_URL"
    )
    goodcang_warehouse_code: str = Field(
        default="", alias="GOODCANG_WAREHOUSE_CODE"
    )
    goodcang_timeout: int = Field(default=30, alias="GOODCANG_TIMEOUT")
    goodcang_max_retry: int = Field(default=3, alias="GOODCANG_MAX_RETRY")

    # ---- 同步任务 ----
    sync_enabled: bool = Field(default=True, alias="SYNC_ENABLED")
    sync_cron: str = Field(default="0 2 * * *", alias="SYNC_CRON")  # 默认每日 02:00


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """提供缓存的 Settings 单例。"""
    return Settings()