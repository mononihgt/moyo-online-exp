# 在线双人战争游戏实验平台

自托管的在线双人实验平台：被试通过姓名和手机号登录，报名具体 Room，在约定时间进入房间，阅读角色指导语，完成配置数量的双人对局，填写 JATOS 后测问卷，并查看被试费与支付状态。主试通过管理端管理白名单、版本、Room、监控、数据和付款。

权威功能规格位于上层目录 `specs/`：

- `specs/SPEC_EXPERIMENT_PLATFORM.md`
- `specs/UI_DESIGN.md`
- `specs/DATA_FORMAT_V4.md`

## 技术组成

- 后端：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MariaDB 10.11、Uvicorn 单 worker。
- 前端：React、TypeScript、Vite，参与者端与管理端共享工程，视觉作用域分开。
- 问卷：JATOS 3.11.x 承载后测问卷；平台提供问卷 schema、签名 token、草稿和幂等双写。
- 部署：Docker Compose、Caddy 自动 HTTPS、MariaDB 双数据库、JATOS 数据卷和备份服务。
- 实时：WebSocket `/ws/room`，进程内连接与计时任务，Room 状态和截止时间持久化到数据库。

## 目录

```text
app/
  api/            参与者、管理端、JATOS、媒体和 WebSocket 路由
  services/       名单、条件、指导语、问卷、Room、运行时、付款、导出
  game/           任意 m×n 战斗引擎和 trial 计划
  main.py         应用工厂、健康检查、安全中间件、前端静态文件
alembic/          数据库迁移
frontend/
  src/participant 参与者端
  src/admin       管理端
  src/questionnaire JATOS 问卷组件
  src/shared      类型、API 客户端和格式化
  e2e             Node Playwright 冒烟测试
tests/
  unit/           引擎、校验、手机号、付款和格式单元测试
  integration/    真实 uvicorn、MariaDB、WebSocket、JATOS 和 Playwright 测试
  e2e/            Python Playwright 双浏览器完整流程
scripts/          JATOS 本地环境、组件上传和备份脚本
docs/             JATOS 测试环境说明
```

## 本地开发

### 依赖

- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 20+ 与 npm
- MariaDB 10.11
- JATOS 3.11.3（macOS 可使用 `scripts/jatos_dev_setup.sh`）
- 运行浏览器测试需要 Chrome；Playwright 默认使用系统 Chrome，可通过 `CHROME_PATH` 指定

### 数据库

本地开发使用独立 MariaDB 实例，端口 `3307`，不依赖系统 3306：

```bash
MARIADB=$(brew --prefix mariadb@10.11)/bin
$MARIADB/mariadb-install-db --datadir="$PWD/../.review/mariadb-data" --auth-root-authentication-method=normal
$MARIADB/mariadbd --datadir="$PWD/../.review/mariadb-data" --port=3307 \
  --bind-address=127.0.0.1 --socket="$PWD/../.review/mariadb-run/mysql.sock" &
$MARIADB/mariadb --protocol=TCP -h127.0.0.1 -P3307 -uroot <<'SQL'
CREATE DATABASE moyo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE moyo_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'moyo'@'127.0.0.1' IDENTIFIED BY 'moyo_dev_password';
GRANT ALL PRIVILEGES ON moyo.* TO 'moyo'@'127.0.0.1';
GRANT ALL PRIVILEGES ON moyo_test.* TO 'moyo'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
```

`.review/` 位于仓库之外，是测试过程目录，任务结束后删除。

### 配置

复制 `.env.example` 作为生产模板；本地开发创建 `.env`：

```dotenv
PUBLIC_BASE_URL=http://127.0.0.1:8000
SECRET_KEY=<openssl rand -hex 32>
PHONE_HMAC_KEY=<openssl rand -hex 32>
PHONE_ENCRYPTION_KEY=<openssl rand -base64 32 | tr '+/' '-_'>
DATABASE_URL=mysql+aiomysql://moyo:moyo_dev_password@127.0.0.1:3307/moyo?charset=utf8mb4
ADMIN_USERNAME=admin
ADMIN_INITIAL_PASSWORD=<至少 12 位密码>
JATOS_BASE_URL=http://127.0.0.1:9000
JATOS_STUDY_CODE=<JATOS study code>
JATOS_API_TOKEN=<JATOS API token>
COOKIE_SECURE=false
TZ=Asia/Shanghai
```

生产环境必须使用 HTTPS，`COOKIE_SECURE=true`，并设置 `TRUST_PROXY_HEADERS=true`。

### 启动

```bash
uv sync
uv run alembic upgrade head
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

必须使用单 worker。匹配队列不保存在进程内，但 WebSocket 连接和运行时定时任务保存在进程内。

首次启动会创建管理员账号并写入内置条件预设 `ref0` 到 `ref5` 和 `asym`。管理员通过 `/admin/login` 登录；参与者通过 `/login` 登录。

开发前端时可单独运行：

```bash
npm --prefix frontend run dev
```

Vite 将 `/api`、`/admin/api`、`/media` 和 `/ws` 代理到 `127.0.0.1:8000`。

## JATOS 问卷

本地 JATOS 环境、REST API、GeneralMultiple 批次启用、组件上传和验证步骤见 `docs/JATOS_TESTING.md`。

平台生成的问卷链接格式：

```text
{JATOS_BASE_URL}/publix/{studyCode}?rt={signed_token}&pid={analysis_code}
```

生产构建问卷组件时通过 `VITE_PLATFORM_BASE_URL` 注入平台地址（Docker Compose 使用 `PUBLIC_BASE_URL` 作为构建参数），并忽略组件 URL 中的 `base` 查询参数。本地测试构建问卷组件时设置 `VITE_ALLOW_BASE_OVERRIDE=true`，之后才能在组件 URL 追加 `base=<平台地址>`；可再用 `VITE_ALLOWED_PLATFORM_ORIGINS` 逗号分隔限制允许来源。

JATOS study 的批次必须允许 `GeneralMultiple`。API 创建的 study 默认只允许 `PersonalSingle` 和 `PersonalMultiple`，需要使用 JATOS 管理界面或 API 打开 `GeneralMultiple`。

问卷组件支持草稿、重新进入、平台双写和按 JATOS result ID 幂等。管理端可以重新签发问卷链接，并手动补齐 JATOS 结果。

## 测试

所有测试使用真实代码、真实 MariaDB、真实 uvicorn、真实 WebSocket 客户端、真实 JATOS 和真实浏览器，不使用 mock。

```bash
# 单元测试（不需要数据库）
uv run pytest tests/unit

# 集成测试（需要 moyo_test 数据库）
uv run pytest tests/integration -m "not jatos"

# 真实 JATOS 双写与问卷组件测试（需要 JATOS 与 API token）
uv run pytest tests/integration/test_jatos.py

# Python Playwright 双浏览器完整流程（需要 Chrome）
uv run pytest tests/e2e

# Node Playwright 冒烟测试（自动启动测试服务器）
npm --prefix frontend run test:e2e
```

JATOS 测试读取 `TEST_JATOS_API_TOKEN`，或读取 `.review/jatos/api_token.env`（由 `scripts/jatos_dev_setup.sh` 生成）。测试会创建独立的 JATOS study，并自动启用 GeneralMultiple。

测试数据库连接可用以下变量覆盖：

```text
TEST_DATABASE_URL
TEST_MYSQL_HOST / TEST_MYSQL_PORT / TEST_MYSQL_USER / TEST_MYSQL_PASSWORD / TEST_MYSQL_DATABASE
TEST_JATOS_BASE_URL / TEST_JATOS_API_TOKEN
PLAYWRIGHT_CHANNEL（Python 浏览器测试，默认 chrome）
CHROME_PATH（Node Playwright）
```

测试过程文件写入上层目录 `.review/`，任务结束后删除。

## 数据与导出

- 统一 `schemaVersion = 4`。
- 完整 Room JSON：`GET /admin/api/rooms/{id}/export.json`。
- 分析 ZIP：`GET /admin/api/rooms/{id}/analysis.zip`，包含 manifest、room、participants、trials、turns、questionnaire、events、payment 和媒体快照。
- 付款名单：`GET /admin/api/payments/export.csv`，包含姓名和手机号，仅管理员可下载，并写入审计日志。
- 分析导出使用假名分析编号 `P-` 加 12 位十六进制，不包含姓名、手机号和内部参与者 UUID。
- 旧 `schemaVersion = 3` 数据不迁移，不提供兼容导出。
- 平台不包含分析脚本。

## 安全

- 手机号使用 HMAC-SHA256 查找和 Fernet 加密存储，日志不记录手机号、token、密码和会话 cookie。
- 管理员密码使用 Argon2。
- 会话 cookie 为 HttpOnly、Secure（HTTPS）和 SameSite=Lax；管理端和参与者写操作校验 CSRF。
- 登录和问卷接口限流。
- 媒体文件通过鉴权路由访问；上传仅接受 PNG、JPEG、WebP，服务端重新编码并剥离 EXIF，不接受 SVG。
- 公开 API 文档关闭。
- 全站建议由 Caddy 终止 HTTPS 并启用 HSTS。

## 部署

生产部署文件位于仓库根目录：

- `Dockerfile`
- `docker-compose.yml`
- `Caddyfile`
- `.env.example`
- `scripts/backup.sh`
- `DEPLOYMENT.md`

部署需要用户提供云服务器、域名和 DNS。`DEPLOYMENT.md` 包含服务器检查清单、密钥生成、JATOS study 与组件配置、证书验证、备份和恢复演练步骤。
