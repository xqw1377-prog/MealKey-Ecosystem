# Seed Environment V1 Runbook

适用目标：阿里云 ECS 上部署 MealKey 的 `Seed Environment V1`，用于 `Pre-production / Seed Store` 验证，不承载生产商户。

## 0. 冻结边界

```text
Infra:
阿里云 ECS
2C4G / 100G ESSD / 5M / Ubuntu 22.04 LTS / 杭州

Runtime:
docker compose

Services:
nginx
api
worker
scheduler
postgres
redis

Allowed:
daily_report_test
DATA-AS-01 test adapter
Truth boundary verification
POIE / ODO validation

Disabled:
production merchant
platform writeback
mock fallback
public database access
authorized session fetch
```

注意：

- 当前仓库线上基线分支仍为 `master`，建议从已验证提交切出 `seed`：

```bash
git checkout -b seed b3dc485
git push -u origin seed
```

- 当前应用的健康检查是 `GET /public/health`，不是裸 `/health`。
- `APP_ENV=seed` 会走“非 dev”护栏，必须提供显式 `JWT_SECRET` 和明确 `CORS_ORIGINS`。

## 1. 阿里云购买参数

- 实例：ECS
- 地域：华东 1（杭州）
- 规格：2 vCPU / 4 GiB
- 系统盘：100 GiB ESSD
- 公网带宽：5 Mbps
- 镜像：Ubuntu 22.04 LTS 64 位

安全组初始最小化：

- `22/tcp`：仅你的办公 IP / VPN IP
- `80/tcp`：可先不开
- `443/tcp`：可先不开

不要开放：

- `5432`
- `6379`
- `8000`

## 2. 服务器初始化

使用 `root` 首次登录后，立即创建非 root 用户：

```bash
adduser mealkey
usermod -aG sudo mealkey
rsync --archive --chown=mealkey:mealkey ~/.ssh /home/mealkey
```

之后切换到 `mealkey`：

```bash
su - mealkey
```

安装基础组件：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git nginx certbot python3-certbot-nginx
```

安装 Docker：

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker mealkey
newgrp docker
```

验证：

```bash
docker --version
docker compose version
git --version
nginx -v
```

## 3. 目录初始化

```bash
sudo mkdir -p /opt/mealkey/{app,docker,data/postgres,data/redis,data/uploads,logs,backup}
sudo chown -R mealkey:mealkey /opt/mealkey
```

目标目录：

```text
/opt/mealkey
├── app
├── docker
├── data
│   ├── postgres
│   ├── redis
│   └── uploads
├── logs
└── backup
```

## 4. 代码部署

```bash
cd /opt/mealkey/app
git clone <your_repo_url> mealky-ai-backend
cd mealky-ai-backend
git fetch --all --tags
git checkout seed
git rev-parse --short HEAD
```

把仓库中的部署模板复制到运行目录：

```bash
mkdir -p /opt/mealkey/docker/nginx
cp deploy/seed/docker-compose.seed.yml /opt/mealkey/docker/docker-compose.seed.yml
cp deploy/seed/nginx.seed.conf /opt/mealkey/docker/nginx/default.conf
cp deploy/seed/.env.seed.example /opt/mealkey/docker/.env.seed
```

## 5. Seed 环境变量

编辑：

```bash
vim /opt/mealkey/docker/.env.seed
```

至少修改这些值：

```env
APP_ENV=seed
DEPLOYMENT_TIER=seed

API_TOKEN=<seed-api-token>
JWT_SECRET=<independent-jwt-secret>

CORS_ORIGINS=https://seed.your-domain.com

DAILY_REPORT_TEST_ENABLED=1
DAILY_REPORT_TEST_BASE_URL=http://49.234.54.78:54321
```

生成密钥示例：

```bash
openssl rand -hex 32
```

说明：

- `DEPLOYMENT_TIER=seed` 当前主要用于运维标识，不是强制代码开关。
- `ENABLE_MOCK=false`、`ENABLE_WRITEBACK=false`、`ENABLE_AUTHORIZED_SESSION=false` 可以作为团队约束保留在 `.env.seed`，但当前代码真正读取的是：
  - `APP_ENV`
  - `DAILY_REPORT_TEST_ENABLED`
  - `DAILY_REPORT_TEST_BASE_URL`
  - `API_TOKEN`
  - `JWT_SECRET`
  - `CORS_ORIGINS`
  - `MEALKEY_DISABLE_CLOCK`

## 6. 启动顺序

进入部署目录：

```bash
cd /opt/mealkey/docker
```

按顺序启动，不要第一次就全部 `up`：

```bash
docker compose --env-file .env.seed -f docker-compose.seed.yml up -d postgres redis
docker compose --env-file .env.seed -f docker-compose.seed.yml up migrate
docker compose --env-file .env.seed -f docker-compose.seed.yml up -d api
docker compose --env-file .env.seed -f docker-compose.seed.yml up -d worker scheduler
docker compose --env-file .env.seed -f docker-compose.seed.yml up -d nginx
```

查看状态：

```bash
docker compose --env-file .env.seed -f docker-compose.seed.yml ps
docker compose --env-file .env.seed -f docker-compose.seed.yml logs -f api
```

## 7. Migration 验收

检查迁移是否完成：

```bash
docker compose --env-file .env.seed -f docker-compose.seed.yml logs migrate
```

检查关键表：

```bash
docker exec -it mealkey-postgres psql -U mealky -d mealky -c "\dt"
```

至少确认存在：

- `stores`
- `business_facts`
- `shop_funnel_daily`
- `action_trace`
- `experiment`
- `strategy_memory`

## 8. 八项验收

### 8.1 API

```bash
curl http://127.0.0.1:8000/public/health
curl http://127.0.0.1:8000/public/readiness
```

### 8.2 Postgres

```bash
docker exec -it mealkey-postgres pg_isready -U mealky -d mealky
```

### 8.3 Redis

```bash
docker exec -it mealkey-redis redis-cli ping
```

### 8.4 Worker / Scheduler

```bash
docker compose --env-file .env.seed -f docker-compose.seed.yml logs --tail=100 worker
docker compose --env-file .env.seed -f docker-compose.seed.yml logs --tail=100 scheduler
```

### 8.5 Test Data Boundary

```bash
curl -H "X-API-Token: <seed-api-token>" http://127.0.0.1:8000/dev/daily-report-test/stores
```

确认测试日报进入 `Evidence`，但不晋升为 `Production Truth`。

### 8.6 Truth Boundary

确认 `daily_report_test` 数据满足：

```text
source=test
truth_eligible=false
```

并且不会污染：

- StoreState production projection
- POIE
- Ranking
- Memory

### 8.7 Action Boundary

对 `COUPON` 相关动作做一次验证，结果必须是：

```text
BLOCKED_NOT_IMPLEMENTED
```

### 8.8 Backup

建立每日备份任务：

```bash
mkdir -p /opt/mealkey/backup
crontab -e
```

加入：

```cron
0 3 * * * cd /opt/mealkey/app/mealky-ai-backend && DATABASE_URL="postgresql://mealky:<password>@127.0.0.1:5432/mealky" BACKUP_DIR="/opt/mealkey/backup" python scripts/backup_postgres.py
30 3 * * * find /opt/mealkey/backup -type f -mtime +7 -delete
```

## 9. Seed 环境显式标识

建议在 UI 顶部固定显示：

```text
SEED ENVIRONMENT
TEST DATA
```

目标是防止团队误把 Seed 当成生产环境。

## 10. 完成后的阶段名

这一步完成后，不叫“上线”，而是进入：

```text
Seed Store Day 0
```

目标：

```text
真实授权店
+ 官方报表
+ Daily Evidence
+ Reconciliation
```

再决定是否进入真正的生产闭环。
