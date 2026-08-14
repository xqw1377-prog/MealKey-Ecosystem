FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production
# 默认留给 compose 注入 Postgres；单容器本地可覆盖为 sqlite:////data/mealky.db
ENV DATABASE_URL=postgresql+psycopg://mealky:mealky@db:5432/mealky

RUN adduser --disabled-password --gecos "" --uid 10001 mealky \
    && mkdir -p /data \
    && chown -R mealky:mealky /app /data

COPY --chown=mealky:mealky requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=mealky:mealky app ./app
COPY --chown=mealky:mealky scripts ./scripts
COPY --chown=mealky:mealky migrations ./migrations
COPY --chown=mealky:mealky alembic.ini .

USER mealky

EXPOSE 8000

# worker/beat 不监听 8000：端口未绑定则视为健康
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python scripts/docker_healthcheck.py

ENTRYPOINT ["python", "scripts/docker_entrypoint.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
