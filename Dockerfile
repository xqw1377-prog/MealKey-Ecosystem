FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production
# 默认留给 compose 注入 Postgres；单容器本地可覆盖为 sqlite:////data/mealky.db
ENV DATABASE_URL=postgresql+psycopg://mealky:mealky@db:5432/mealky

# 独立部署：镜像只含本仓代码与内置 llm_engine，不含主仓依赖、不烘焙 API Key
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /data

EXPOSE 8000

# 运行时通过 compose env_file / 环境变量注入 DEEPSEEK_/QWEN_/MOONSHOT_ 等密钥
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
