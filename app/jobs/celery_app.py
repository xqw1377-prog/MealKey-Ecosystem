from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "mealkey_ai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.jobs.tasks"],
)
celery_app.conf.update(
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        # === 原有定时 ===
        "collect-competition-snapshots-daily": {
            "task": "competition.collect_all_stores",
            "schedule": crontab(
                hour=settings.competition_collection_hour,
                minute=settings.competition_collection_minute,
            ),
        },
        "run-daily-job-all-stores": {
            "task": "ops.run_daily_job_all_stores",
            "schedule": crontab(
                hour=settings.daily_job_hour,
                minute=settings.daily_job_minute,
            ),
        },
        "attribute-experiments-all-stores": {
            "task": "ops.attribute_experiments_all_stores",
            "schedule": crontab(
                hour=settings.daily_job_hour,
                minute=settings.daily_job_minute + 30,
            ),
        },
        # === Daily Operating Clock（材料 §五 6 个经营节点）===
        "morning-readiness-check": {
            "task": "ops.operating_clock",
            "args": ("morning_readiness",),
            "schedule": crontab(hour=9, minute=30),  # 开业后：今日准备度检查
        },
        "lunch-nba": {
            "task": "ops.operating_clock",
            "args": ("lunch_nba",),
            "schedule": crontab(hour=10, minute=30),  # 午高峰前：Next Best Action
        },
        "lunch-protect": {
            "task": "ops.operating_clock",
            "args": ("lunch_protect",),
            "schedule": crontab(hour=11, minute=50),  # 午高峰：Protect Mode 实时监控
        },
        "lunch-review": {
            "task": "ops.operating_clock",
            "args": ("lunch_review",),
            "schedule": crontab(hour=14, minute=0),  # 餐段复盘
        },
        "evening-light-review": {
            "task": "ops.operating_clock",
            "args": ("evening_review",),
            "schedule": crontab(hour=21, minute=0),  # 晚间轻复盘
        },
        # V1 补全时段
        "dinner-strategy": {
            "task": "ops.operating_clock",
            "args": ("dinner_strategy",),
            "schedule": crontab(hour=16, minute=30),  # 晚餐前策略调整
        },
        "deep-review": {
            "task": "ops.operating_clock",
            "args": ("deep_review",),
            "schedule": crontab(hour=6, minute=0),  # 次日凌晨数据完整后深度复盘
        },
        "night-learn": {
            "task": "ops.operating_clock",
            "args": ("night_learn",),
            "schedule": crontab(hour=2, minute=0),  # 凌晨数据结算后回收实验+更新画像
        },
        # Weekly/Monthly Playbook（V1 §14-15）
        "weekly-playbook": {
            "task": "ops.operating_clock",
            "args": ("weekly_playbook",),
            "schedule": crontab(hour=7, minute=0, day_of_week=1),  # 每周一 7:00
        },
        "monthly-playbook": {
            "task": "ops.operating_clock",
            "args": ("monthly_playbook",),
            "schedule": crontab(hour=7, minute=0, day_of_month=1),  # 每月 1 号 7:00
        },
    },
)
