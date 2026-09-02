"""GoodCang Cost Intelligence 后端应用包。

统一对外入口 `app` 命名空间，按职责划分子模块：
- core        ：配置、数据库连接、日志
- connectors  ：第三方 API 连接器（GoodCang）
- models      ：SQLAlchemy ORM 模型
- schemas     ：Pydantic 数据传输模型
- repositories：数据访问层
- services    ：业务逻辑/分析引擎
- api.routes  ：FastAPI 路由
- tasks       ：定时同步任务
"""