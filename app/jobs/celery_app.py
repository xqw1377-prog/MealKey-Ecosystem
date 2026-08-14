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
        "collect-platform-intel-daily": {
            "task": "platform_intel.collect_official",
            "schedule": crontab(
                hour=settings.platform_intel_hour,
                minute=settings.platform_intel_minute,
            ),
        },
        "diff-p0-rule-sources-weekly": {
            "task": "oci.diff_p0_rules",
            "schedule": crontab(hour=6, minute=20, day_of_week="sun"),
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
        # WP1: 节律心跳 —— 每 30 分钟一次，逐店按自己的经营节律命中 phase
        "rhythm-tick": {
            "task": "ops.rhythm_tick",
            "schedule": crontab(minute="*/30"),
        },
        # 旧的全网硬编码 crontab 已废弃：operating_clock 仍保留供手动/测试调用

        # WP3: 决策流跟进——每小时检查到期的 next_check_at
        "follow-up-decisions": {
            "task": "ops.follow_up_decisions",
            "schedule": crontab(minute="*/60"),
        },
    },
)
