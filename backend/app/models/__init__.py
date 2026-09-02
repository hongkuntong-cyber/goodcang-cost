"""ORM 模型层：与数据库表一一对应。

约定：
- 表名一律带前缀：`stg_*`（原始层）/ `mart_*`（分析层）/ `dim_*`（维度）/ 其他运维
- 字段命名使用 snake_case；枚举值使用小写字符串（如 fee_category='storage'）
- 所有模型继承自 app.core.database.Base

按 domain 拆分文件，便于扩展：
- dim.py      : 维度/参考表
- stg.py      : 原始层（账单、费用明细、库存快照）
- mart.py     : 分析层（月度汇总、风险SKU、月度报告）
- ops.py      : 运维（同步日志）
"""
from app.models.dorm import *  # noqa: F401,F403
from app.models.mart import *  # noqa: F401,F403
from app.models.ops import *  # noqa: F401,F403
from app.models.stg import *  # noqa: F401,F403