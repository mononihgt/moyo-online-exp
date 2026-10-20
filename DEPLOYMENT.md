# 部署与运维

本文件是单服务器部署检查清单。服务器、域名和 DNS 必须由部署者提供；下文中的 `<平台域名>`、`<JATOS域名>`、`<服务器IP>`、`<仓库地址>` 都需要替换成真实值。`.env.example` 中的 example.com 不能用于正式实验。

## 1. 前置条件

服务器建议：

- Ubuntu 24.04 LTS。
- 2 vCPU、4 GB 内存、40 GB SSD。
- 固定公网 IP。
- 入站开放 SSH、80/tcp、443/tcp、443/udp。
- 不向公网开放 8000、3306、9000。这些端口只在 Compose 内部网络中可达。

域名准备：

- 一个平台域名，例如 `game.example.com`。
- 一个 JATOS 域名，例如 `jatos.example.com`。
- 两个域名的 A 记录都指向服务器 IP，并等待 DNS 生效。

检查 DNS：

```bash
getent ahostsv4 <平台域名> | head -1
getent ahostsv4 <JATOS域名> | head -1
```

安装 Docker Engine 和 Compose v2：

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

重新登录 SSH 终端后检查：

```bash
docker --version
docker compose version
```

服务器需要能拉取 Docker Hub 与 `ghcr.io` 的镜像，并能在构建时访问 npm 仓库。

把仓库放到 `/opt/moyo`。仓库地址由部署者提供：

```bash
sudo mkdir -p /opt/moyo
sudo chown "$USER":"$USER" /opt/moyo
git clone <仓库地址> /opt/moyo
cd /opt/moyo
```

防火墙：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
sudo ufw status
```

## 2. 文件职责

- `Dockerfile`：两阶段构建。Node 构建 `frontend/dist` 与 `frontend/dist-questionnaire`，Python 安装 `uv.lock` 中的依赖，构建产物保留在 `frontend/dist` 和 `frontend/dist-questionnaire`，以非 root 用户运行。`PUBLIC_BASE_URL` 通过构建参数 `VITE_PLATFORM_BASE_URL` 注入问卷组件。生产构建不设置 `VITE_ALLOW_BASE_OVERRIDE`，问卷 URL 中的 `base` 查询参数会被忽略。
- `docker-compose.yml`：`caddy`、`app`、`db`、`jatos`、`backup` 五个服务，全部使用命名卷。
- `Caddyfile`：两个域名分别反向代理到 `app:8000` 和 `jatos:9000`，自动申请 TLS 证书。平台站点有 25 MB 请求体上限和安全响应头。
- `.env.example`：环境变量模板。实际使用的 `.env` 不提交到仓库。
- `scripts/backup.sh`：备份两个数据库、平台数据卷和 JATOS 数据卷，执行每日与每周保留策略。

Compose 项目名固定为 `moyo`，因此命名卷是：

```text
moyo_db_data
moyo_app_data
moyo_jatos_data
moyo_caddy_data
moyo_caddy_config
moyo_backup_data
```

## 3. 生成密钥并配置 .env

生成数据库和信息安全相关密钥：

```bash
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 32   # PHONE_HMAC_KEY
openssl rand -base64 32 | tr '+/' '-_'   # PHONE_ENCRYPTION_KEY
openssl rand -base64 32 | tr '+/' '-_'   # IDENTITY_ENCRYPTION_KEY
openssl rand -hex 24   # MYSQL_ROOT_PASSWORD
openssl rand -hex 24   # MYSQL_PASSWORD
openssl rand -hex 24   # JATOS_DB_PASSWORD
openssl rand -hex 32   # JATOS_SECRET
openssl rand -hex 16   # ADMIN_INITIAL_PASSWORD
```

写入 `.env`：

```bash
cp .env.example .env
chmod 600 .env
```

需要填写的值：

| 变量 | 说明 |
| --- | --- |
| `APP_DOMAIN` | 平台域名主机名，不带协议 |
| `PUBLIC_BASE_URL` | 平台的公网地址，必须是 `https://` |
| `JATOS_DOMAIN` | JATOS 域名主机名，不带协议 |
| `JATOS_BASE_URL` | JATOS 的公网地址，必须是 `https://` |
| `SECRET_KEY` | 登录状态和签名密钥，64 位十六进制 |
| `PHONE_HMAC_KEY` | 手机号查询索引的 HMAC 密钥 |
| `PHONE_ENCRYPTION_KEY` | 手机号加密的 Fernet 密钥 |
| `IDENTITY_ENCRYPTION_KEY` | 受保护问卷字段（真实姓名、支付宝手机号和身份证明）的 Fernet 密钥，必须与 `PHONE_ENCRYPTION_KEY` 不同 |
| `MYSQL_ROOT_PASSWORD` | MariaDB root 密码 |
| `MYSQL_PASSWORD` | 平台数据库用户 `moyo` 的密码 |
| `DATABASE_URL` | 已由 `MYSQL_PASSWORD` 插值生成，保持默认写法 |
| `JATOS_DB_PASSWORD` | JATOS 数据库用户 `jatos` 的密码 |
| `ADMIN_USERNAME` | 管理端用户名 |
| `ADMIN_INITIAL_PASSWORD` | 管理员初始密码 |
| `JATOS_STUDY_CODE` | JATOS study code，JATOS 配置完成后填写 |
| `JATOS_API_TOKEN` | JATOS API token，JATOS 配置完成后填写 |
| `JATOS_SECRET` | JATOS 登录状态密钥，首次启动后不要更换 |
| `COOKIE_SECURE` | 正式环境保持 `true` |
| `LOG_LEVEL` | 默认 `INFO` |
| `TZ` | 默认 `Asia/Shanghai` |

密码只使用十六进制字符，避免破坏 `DATABASE_URL` 和初始化 SQL。`.env` 只保存在服务器上，权限保持 `600`。

检查 Compose 变量插值是否完整：

```bash
docker compose config --quiet
```

以下值在首次启动后不要随意更换：

- `SECRET_KEY`：更换会使现有登录状态失效。
- `JATOS_SECRET`：更换会影响 JATOS 的登录状态和内部签名。
- `IDENTITY_ENCRYPTION_KEY`：更换会使已保存的真实姓名、支付宝手机号和证件号码无法解密。该密钥必须与数据库、媒体和 JATOS 备份分开保存，并保留至少一份异地副本。
- `MYSQL_PASSWORD`、`JATOS_DB_PASSWORD`：MariaDB 只在数据卷首次初始化时使用这些值创建用户。直接修改 `.env` 不会更新数据库中的密码，会导致应用无法连接。必须先在数据库中修改用户密码，再同步修改 `.env`。

## 4. 首次启动

构建镜像：

```bash
cd /opt/moyo
docker compose build
```

先启动数据库，等待健康检查通过：

```bash
docker compose up -d db
docker compose ps
```

`db` 显示 `healthy` 后再执行数据库迁移：

```bash
docker compose run --rm app uv run --no-sync alembic upgrade head
```

启动全部服务：

```bash
docker compose up -d
docker compose ps
```

五个服务都应为 `running`，`db`、`app`、`jatos` 应为 `healthy`。查看启动日志：

```bash
docker compose logs --tail=100 app
docker compose logs --tail=100 jatos
docker compose logs --tail=100 caddy
```

单 worker 是硬性要求。不要修改 `--workers 1`，不要对 `app` 做水平扩展。

## 5. 管理员账号

平台使用单管理员账号。应用启动时检查 `admin_users` 表：表为空时使用 `ADMIN_USERNAME` 和 `ADMIN_INITIAL_PASSWORD` 创建管理员；表中已有管理员时不会覆盖。因此初始密码只在第一次启动时生效，修改 `.env` 不会改变已有账号的密码。

部署后打开管理端登录页，使用这组账号登录，确认登录成功后再进行正式实验配置。

管理员密码属于生产凭据，不要写入仓库、聊天记录或工单。

## 6. JATOS 配置

JATOS 首次启动会自动在 `jatos` 数据库中创建表。管理员入口：

```text
https://<JATOS域名>/jatos/admin
```

JATOS 默认管理员是 `admin / admin`。首次启动后立即登录并修改密码。在密码修改完成前，不要把 JATOS 域名和入口告知参与者，也不要发布任何参与链接。

问卷组件使用 JATOS `GeneralMultiple` 运行：所有 Room 共用一个 study code，平台在链接后追加 `rt` 与 `pid`。JATOS 的 API 默认批次只允许 `PersonalSingle` 和 `PersonalMultiple`；部署脚本会自动把默认批次改为同时允许 `GeneralMultiple`。如果手工创建 study，必须在 JATOS 管理界面打开 GeneralMultiple，否则链接会提示 worker type 不允许。

配置步骤：

1. 登录 JATOS 管理端，修改默认管理员密码。
2. 点击右上角用户名，进入 My API tokens，新建一个管理员 token。token 只显示一次。
3. 在 `.env` 中填写 `JATOS_BASE_URL` 和 `JATOS_API_TOKEN`，启动数据库与应用容器：

   ```bash
   docker compose up -d db app
   ```

4. 在应用容器中运行部署脚本。脚本会创建 study、启用 GeneralMultiple、上传 `frontend/dist-questionnaire` 的全部构建资产、创建 HTML 组件和 study code：

   ```bash
   docker compose exec app uv run --no-sync python scripts/deploy_jatos_questionnaire.py \
     --title "Moyo 后测问卷"
   ```

   输出中的 `studyCode` 就是平台需要的 study code。脚本不打印 API token。若已有 study，可加 `--study <studyIdOrUuid>` 复用；重复运行会创建新的组件和 code。

5. 把 study code 填入 `.env` 的 `JATOS_STUDY_CODE`，或登录平台管理端在设置页填写。数据库设置优先于环境变量。然后重建应用：

   ```bash
   docker compose up -d --force-recreate app
   ```

6. 在管理端创建测试 Room，生成问卷链接，用浏览器确认：

   - JATOS 页面加载后显示平台问卷标题。
   - 平台收到的 `rt`、`pid` 与 JATOS `urlQueryParameters` 一致。
   - 提交后 JATOS 结果和平台问卷记录同时存在。
   - 完成后跳转平台 `/complete` 页面。

`JATOS_API_TOKEN` 只保存在服务器 `.env` 中，不能写入前端代码或浏览器可见的位置。问卷组件的平台地址在镜像构建时由 `PUBLIC_BASE_URL` 注入，修改平台域名后需要重新构建镜像。

## 7. HTTPS 与功能验证

证书由 Caddy 自动申请。确认 Caddy 日志中没有 ACME 错误：

```bash
docker compose logs --tail=200 caddy
```

检查 HTTPS、健康检查和响应头：

```bash
curl -fsS https://<平台域名>/healthz
curl -sSI https://<平台域名>/ | sed -n '1,20p'
curl -sSI https://<JATOS域名>/jatos/admin | sed -n '1,10p'
```

确认：

- `/healthz` 返回成功 JSON。
- 响应包含 `Strict-Transport-Security`、`X-Content-Type-Options: nosniff`，没有 `Server` 头。
- HTTP 自动重定向到 HTTPS。
- JATOS 管理端可以登录。

WebSocket 和完整流程验证：

1. 用两个独立浏览器上下文分别登录两名参与者。
2. 完成报名、进入 Room、指导语确认和对局。
3. 在浏览器开发者工具中确认 `/ws/room` 连接返回 `101 Switching Protocols`，页面没有混合内容警告。
4. 完成一个 Room 的后测问卷，检查平台管理端能看到 JATOS 结果 ID 和问卷状态。在开发者工具中确认问卷页面的脚本、样式和 `jatos.js` 都返回 200，没有 404。
5. 检查分析导出和付款名单。

上传一张图片，确认平台图片上传正常。请求超过 25 MB 时 Caddy 应返回 413。

## 8. 备份

`backup` 服务在容器启动后每天 `02:00`（`Asia/Shanghai`）执行一次备份。容器启动时如果当天还没有备份，会立即补一次。每次备份包含：

- `moyo.sql.gz`
- `jatos.sql.gz`
- `app_data.tar.gz`（平台数据卷，包含媒体文件）
- `jatos_data.tar.gz`（JATOS 数据卷）
- `SHA256SUMS`
- `manifest.txt`

自动备份不包含 `.env`。`IDENTITY_ENCRYPTION_KEY` 必须单独保存在凭据管理系统或离线介质中，并至少保留一份异地副本。数据库恢复后必须使用同一密钥解密身份记录；密钥丢失会使已保存的真实姓名、支付宝手机号和证件号码无法恢复。

目录结构与保留策略：

- `/backups/daily/<时间戳>/`：保留 7 份。
- `/backups/weekly/<ISO周>/`：每周第一份备份以硬链接方式保存，保留 4 周。
- 备份先写入 `.incomplete-*` 临时目录，成功后才改名。失败不会留下半份备份。
- 同一时间只允许一个备份进程运行。

手动备份：

```bash
cd /opt/moyo
docker compose run --rm backup once
```

查看和校验备份：

```bash
docker compose exec backup ls -lah /backups/daily /backups/weekly
docker compose exec backup cat /backups/daily/<时间戳>/manifest.txt
docker compose exec backup bash -c 'cd /backups/daily/<时间戳> && sha256sum -c SHA256SUMS'
```

数据库使用 `mariadb-dump --single-transaction`。媒体文件和 JATOS 数据使用 `tar`，备份过程中服务保持运行，因此跨数据库与文件系统的一致性按每日快照对待。

备份卷在宿主机上是 Docker 命名卷，必须定期同步到另一台服务器或对象存储。示例：先导出到宿主机目录，再用 `rsync` 同步：

```bash
sudo install -d -m 700 /srv/moyo-offsite
docker run --rm \
  -v moyo_backup_data:/backups:ro \
  -v /srv/moyo-offsite:/dest \
  alpine:3.20 \
  cp -a /backups/. /dest/
rsync -a --delete /srv/moyo-offsite/ <备份服务器>:/srv/moyo-backups/
```

对象存储、快照或异地服务器至少选择一种。只保留服务器本地备份无法应对整机故障。

备份包含姓名、手机号密文、证件号码密文和 JATOS 结果，属于研究数据和个人信息。备份目录在容器内权限为 `700`，文件为 `600`。异地存储应使用加密传输和加密存储，并限制访问人员。

## 9. 恢复演练

正式实验前至少完成一次恢复演练。恢复会覆盖当前数据，演练应在临时服务器或临时卷上进行；在生产服务器执行前必须先做一次手动备份。

恢复同一个备份时间戳的数据库与文件，不能混用不同日期。整机灾难恢复建议使用全新的数据库卷和 JATOS 数据卷，从空库开始导入，避免旧表残留。下面的命令适用于在已经初始化过的卷上恢复同一套 schema 的快照。

JATOS 临时目录不进入备份。

停止应用写入：

```bash
cd /opt/moyo
docker compose stop app jatos
```

先校验备份完整性：

```bash
docker compose exec backup bash -c 'cd /backups/daily/<时间戳> && sha256sum -c SHA256SUMS'
```

恢复数据库：

```bash
docker compose run --rm --entrypoint bash backup -c \
  'gunzip -c /backups/daily/<时间戳>/moyo.sql.gz | MYSQL_PWD="$DB_ROOT_PASSWORD" mariadb -h db -uroot moyo'

docker compose run --rm --entrypoint bash backup -c \
  'gunzip -c /backups/daily/<时间戳>/jatos.sql.gz | MYSQL_PWD="$DB_ROOT_PASSWORD" mariadb -h db -uroot jatos'
```

恢复平台数据卷：

```bash
docker run --rm \
  -v moyo_app_data:/data \
  -v moyo_backup_data:/backups:ro \
  --entrypoint tar \
  mariadb:10.11 \
  -xzf /backups/daily/<时间戳>/app_data.tar.gz -C /data --strip-components=1
```

恢复 JATOS 数据卷：

```bash
docker run --rm \
  -v moyo_jatos_data:/data \
  -v moyo_backup_data:/backups:ro \
  --entrypoint tar \
  mariadb:10.11 \
  -xzf /backups/daily/<时间戳>/jatos_data.tar.gz -C /data --strip-components=1
```

数据库和文件备份不包含 `IDENTITY_ENCRYPTION_KEY`。恢复 `.env` 时必须使用加密身份记录时的同一密钥；从独立安全副本取得该密钥，不能重新生成。缺少原密钥时，`participant_identities` 中的真实姓名、支付宝手机号和证件号码无法解密。

启动服务并验证：

```bash
docker compose up -d
docker compose ps
curl -fsS https://<平台域名>/healthz
```

然后登录管理端，检查参与者、Room、导出和 JATOS 结果。恢复后如健康检查失败，查看 `docker compose logs app db jatos`，不要继续写入数据。

## 10. 升级流程

迁移 `5b8e2f4c9a71` 是破坏性迁移。从 v4 升级时，它删除全部 Room、预约、参与者关联、trial、回合、回合提交、问卷草稿、问卷响应、付款、事件、计时器和配置修订，删除全部旧指导语版本，删除 `condition_versions` 表，并从 `rooms` 删除旧条件外键和 Room 级费用字段。参与者记录、问卷版本、同意书版本和管理员账号保留。部署时不再需要预导入未来参与者名单；参与者首次登录自动创建账号，历史参与者通过管理端「导入历史已完成名单」初始化完成状态。平台不提供 v4 数据读取路径；降级迁移只恢复表结构，不恢复已删除的数据。

执行迁移前必须完成完整备份，并确认 `.env` 中的 `IDENTITY_ENCRYPTION_KEY` 有独立安全副本。

1. 先手动备份：

```bash
cd /opt/moyo
docker compose run --rm backup once
```

2. 拉取新版本并构建：

```bash
git pull
docker compose build app
```

3. 执行数据库迁移：

```bash
docker compose run --rm app uv run --no-sync alembic upgrade head
```

4. 重建应用容器：

```bash
docker compose up -d app caddy
```

如果 `scripts/backup.sh` 有变化，重建备份容器使新脚本生效：

```bash
docker compose up -d --force-recreate backup
```

5. 检查：

```bash
docker compose ps
curl -fsS https://<平台域名>/healthz
docker compose logs --tail=100 app
```

升级期间进行中的 Room 会中断。安排在没有实验的时段，并提前通知主试。

回滚时回到上一个提交并重新构建镜像。数据库迁移如果已经改变表结构，必须用升级前的备份恢复；不要假定迁移可以无损降级。

## 11. 日常检查

每天或每次实验前检查：

```bash
cd /opt/moyo
docker compose ps
docker compose logs --tail=50 app caddy
docker compose exec backup ls -lah /backups/daily
df -h
docker system df
```

重点关注：

- `app`、`db`、`jatos` 健康状态。
- Caddy 证书续期日志。
- 备份是否按日生成，异机副本是否更新。
- 磁盘空间。JATOS 结果上传和平台媒体会持续增长。
- 服务器时间同步。登录状态过期和签名校验依赖准确的系统时间。

故障排查起点：

```bash
docker compose logs --tail=200 app
docker compose logs --tail=200 db
docker compose logs --tail=200 jatos
docker compose logs --tail=200 caddy
```

数据库进程异常时不要删除 `moyo_db_data` 卷。先保留现场、复制备份，再排查。

## 12. 已知限制

- 单服务器、单 worker，不支持水平扩展、多 worker 或跨服务器恢复进行中的 Room。
- 备份是每日逻辑快照，恢复粒度最细到一天。接受最多约 24 小时的数据丢失窗口。
- 异地备份需要部署者自行配置并定期验证。
- JATOS 组件和平台问卷的兼容性需要在部署后用一个真实 Room 验证。
