# 后端运行镜像
FROM python:3.13-slim

WORKDIR /app

# 依赖单独一层，便于缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 启动前跑迁移，再启动 uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
