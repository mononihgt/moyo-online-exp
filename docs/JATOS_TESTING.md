# JATOS 3.11.3 本地测试环境

本文记录在 macOS arm64 上实际搭建并验证过的 JATOS 3.11.3 环境、REST API 调用、问卷组件上传流程，以及 JATOS 3.11.3 与 3.12.0 的差异。未实际验证的内容会单独标注。

## 目录与端口

| 内容 | 默认位置 |
| --- | --- |
| JATOS 安装目录 | `.review/jatos/jatos_mac_aarch64_java` |
| JATOS 安装包 | `.review/jatos/jatos_mac_aarch64_java.zip` |
| JATOS 日志 | `.review/jatos/jatos_mac_aarch64_java/logs/application.log` |
| JATOS 临时目录 | `.review/jatos/tmp` |
| MariaDB 数据目录 | `.review/mariadb-data` |
| MariaDB 运行文件 | `.review/mariadb-run` |
| 数据库密码文件 | `.review/jatos/jatos_db.env` |
| API token 文件 | `.review/jatos/api_token.env` |

`.review/` 位于独立仓库 `moyo-online-exp/` 之外，不提交到 git。JATOS 端口为 `127.0.0.1:9000`，MariaDB 端口为 `127.0.0.1:3307`。安装包内自带 Temurin Java 11.0.29，使用 MySQL Connector/J 8.0.28，MariaDB 版本为 10.11.19。

## 一键启动

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo/moyo-online-exp
./scripts/jatos_dev_setup.sh
```

脚本行为：

1. 检测 `http://127.0.0.1:9000/ping`。返回 `pong` 时复用运行中的实例。
2. 检测 MariaDB 的 TCP 连接。未运行时使用 `.review/mariadb-data` 初始化并启动 MariaDB。
3. 创建或更新数据库 `jatos` 与用户 `jatos@127.0.0.1`。数据库密码优先取环境变量 `JATOS_DB_PASSWORD`，其次复用 `.review/jatos/jatos_db.env`；环境变量未设置且文件不存在时随机生成。密码写入权限为 `600` 的文件，不会出现在命令行参数中。
4. 检测安装包与安装目录。存在且 `VERSION` 为 `3.11.3` 时直接复用；安装包缺失时下载 `jatos_mac_aarch64_java.zip`，支持断点续传，并用 `unzip -t` 校验。
5. 写入 `conf/jatos.conf`，设置 HTTP 端口、数据库连接、临时目录和 API token 有效期。
6. 启动 JATOS 并轮询 `/ping`，最多等待 180 秒。
7. 用管理员账号登录后生成 API token，写入 `api_token.env`。已有 token 会先用 `GET /jatos/api/v1/admin/token` 验证，失效后自动重建。
8. 输出 `JATOS_BASE_URL`、JATOS PID、日志路径、数据库连接信息、token 文件位置和停止命令。

可覆盖的环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `JATOS_ROOT` | `<项目根目录>/.review/jatos` | 安装包、配置、token 的存放目录 |
| `JATOS_HOME` | `$JATOS_ROOT/jatos_mac_aarch64_java` | 解压后的 JATOS 目录 |
| `JATOS_PORT` | `9000` | JATOS HTTP 端口 |
| `JATOS_DB_PORT` | `3307` | MariaDB 端口 |
| `JATOS_DB_NAME` | `jatos` | 数据库名称 |
| `JATOS_DB_USER` | `jatos` | 数据库用户 |
| `JATOS_DB_PASSWORD` | 随机生成 | 数据库用户密码；设置后写入 `jatos_db.env` 并用于数据库配置 |
| `JATOS_ADMIN_USER` | `admin` | 生成 API token 时登录的 JATOS 用户 |
| `JATOS_ADMIN_PASSWORD` | `admin` | 登录密码，只用于生成 token，不修改管理员密码 |
| `MARIADB_ROOT_USER` | `root` | 管理 MariaDB 的用户 |
| `MARIADB_ROOT_PASSWORD` | 空 | MariaDB 管理密码 |
| `MARIADB_DATA_DIR` | `<项目根目录>/.review/mariadb-data` | MariaDB 数据目录 |
| `MARIADB_RUN_DIR` | `<项目根目录>/.review/mariadb-run` | socket 和 pid 文件目录 |
| `MARIADB_LOG` | `<项目根目录>/.review/mariadb-server.log` | MariaDB 错误日志 |

本机当前 MariaDB 使用团队指定的 `jatos` 用户与密码，实际密码保存在 `.review/jatos/jatos_db.env`，权限为 `600`。MariaDB 只监听 `127.0.0.1:3307`，不使用 3306。

脚本幂等：JATOS 已健康运行时只复用并检查 token。JATOS 进程存在但 `/ping` 不健康时，脚本直接报错并提示先停止进程，不会自动结束进程。

停止命令：

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo/.review/jatos/jatos_mac_aarch64_java
./loader.sh stop
```

```bash
/opt/homebrew/opt/mariadb@10.11/bin/mariadb-admin \
  --protocol=TCP -h 127.0.0.1 -P 3307 -u root shutdown
```

### 管理员账号

JATOS 3.11.3 首次启动创建的管理员账号为 `admin` / `admin`。本次安装后检索 `application.log`，没有随机初始密码输出；JATOS 官方安装文档也只说明默认口令。`scripts/jatos_dev_setup.sh` 不修改管理员密码。修改过密码后，重跑脚本时设置 `JATOS_ADMIN_PASSWORD`，否则 token 自动创建会失败并给出提示，此时可以在界面中手动创建 token。

管理员界面地址为 `http://127.0.0.1:9000/jatos`。

## API 认证

API 前缀为 `/jatos/api/v1`。带 token 的请求使用：

```text
Authorization: Bearer jap_...
```

### 通过管理员登录生成 token

JATOS 3.11.3 的 token 创建接口允许使用管理员登录产生的 cookie 认证。先用管理员账号登录，再创建 token。登录接口没有标记 `nocsrf`，需要发送 `Authorization` 头才能跳过 CSRF 检查；`csrf-bypass` 不含 `Bearer`，不会切换到 token 认证。

```bash
BASE_URL=http://127.0.0.1:9000
COOKIE_JAR=.review/jatos/.admin-cookies.txt

curl -sS -c "$COOKIE_JAR" \
  -H 'Authorization: csrf-bypass' \
  --data-urlencode 'username=admin' \
  --data-urlencode 'password=admin' \
  "$BASE_URL/jatos/signin/local"
```

本次实际响应：

```json
{"redirectUrl":"/jatos","userSigninTime":1792262806599}
```

读取管理员用户 ID：

```bash
curl -sS -b "$COOKIE_JAR" \
  -H 'Authorization: csrf-bypass' \
  "$BASE_URL/jatos/api/v1/users"
```

实际响应：

```json
{"apiVersion":"1.1.0","data":[{"id":1,"username":"admin","name":"Admin"}]}
```

创建 token：

```bash
curl -sS -b "$COOKIE_JAR" \
  -H 'Authorization: csrf-bypass' \
  -H 'Content-Type: application/json' \
  -d '{"name":"moyo-dev"}' \
  "$BASE_URL/jatos/api/v1/users/1/tokens"
```

实际响应的字段如下，`token` 的值已替换：

```json
{
  "apiVersion": "1.1.0",
  "data": {
    "id": 3,
    "name": "docs-shape",
    "creationDate": 1792262806650,
    "active": true,
    "expiresAfter": 86400,
    "expirationDate": 1792349206650,
    "username": "admin",
    "roles": ["USER", "ADMIN"],
    "userId": 1,
    "isExpired": false,
    "token": "<redacted>"
  }
}
```

token 以 `jap_` 开头，只在创建时返回一次。`api_token.env` 权限为 `600`，内容只有一行：

```text
JATOS_API_TOKEN=jap_...
```

在 shell 中加载：

```bash
set -a
. .review/jatos/api_token.env
set +a
```

`scripts/jatos_api.py` 只使用 Python 标准库，已在 Python 3.9.6 和 Python 3.12.13 下对真实 JATOS 实例调用成功。客户端从环境变量读取 `JATOS_BASE_URL`、`JATOS_API_TOKEN`、`JATOS_STUDY_CODE`。`JATOS_BASE_URL` 未设置时使用 `http://127.0.0.1:9000`。`JATOS_STUDY_CODE` 在这个客户端中表示 study 的 id 或 uuid；参与者链接里的 studyCode 是另一个字段。

token 有效期在 `conf/jatos.conf` 中设置为 86400 秒。数据库 `ApiToken.expires` 和创建响应中的 `expiresAfter` 均为 86400，已实测。脚本输出中也提示本配置中 token 有效期 1 天。

验证 token：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  "http://127.0.0.1:9000/jatos/api/v1/admin/token"
```

实际返回 `200`。

## Study、资产与组件

### 创建 study

```bash
curl -sS \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Moyo JATOS Integration Test","active":true,"groupStudy":false,"linearStudy":false,"allowPreview":false}' \
  "http://127.0.0.1:9000/jatos/api/v1/studies" |
  jq '{apiVersion, id: .data.id, uuid: .data.uuid, dirName: .data.dirName, batch: .data.batches[0]}'
```

本次实际返回：

```json
{
  "apiVersion": "1.1.0",
  "id": 1,
  "uuid": "75441d28-cd5f-4c3d-b126-baeb4d00d6d7",
  "dirName": "75441d28-cd5f-4c3d-b126-baeb4d00d6d7",
  "batch": {"id": 1, "uuid": "d2384b26-fa6f-4e4f-8634-68c4127975ec"}
}
```

响应中的 `data.id` 和 `data.uuid` 都可以作为后续路径参数。API 没有 `GET /studies` 列表接口，实际返回 404。

### study 资产

JATOS 3.11.3 没有组件级资产接口。HTML、JS、CSS、图片都上传到 study 资产目录，组件通过 `htmlFilePath` 引用 HTML。

单文件上传：

```bash
curl -sS \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  -F 'studyAssetsFile=@frontend/dist-questionnaire/questionnaire.html;filename=questionnaire.html' \
  "http://127.0.0.1:9000/jatos/api/v1/studies/2/assets/questionnaire.html"
```

实际响应：

```json
{"apiVersion":"1.1.0","message":"File uploaded successfully"}
```

multipart 字段名必须是 `studyAssetsFile`。嵌套路径会创建目录，例如把 `assets/probe.js` 上传到：

```bash
curl -sS \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  -F 'studyAssetsFile=@frontend/dist-questionnaire/assets/probe.js;filename=probe.js' \
  "http://127.0.0.1:9000/jatos/api/v1/studies/2/assets/assets/probe.js"
```

查看资产结构：

```bash
curl -sS \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  "http://127.0.0.1:9000/jatos/api/v1/studies/2/assets/structure?flatten=true"
```

实际返回：

```json
{
  "apiVersion": "1.1.0",
  "data": [
    {"name":"questionnaire.html","path":"questionnaire.html","type":"file","size":303},
    {"name":"probe.js","path":"assets/probe.js","type":"file","size":434}
  ]
}
```

`flatten=false` 时返回树形结构。每个文件包含 `path`、`type`、`creation`、`lastModified`、`size`、`checksum`。

### 创建 HTML 组件

```bash
python3 scripts/jatos_api.py create-component \
  --study 2 \
  --title "Questionnaire" \
  --html-file questionnaire.html \
  --comments "Platform questionnaire component"
```

实际使用脚本创建的组件响应中的关键字段：

```json
{
  "apiVersion": "1.1.0",
  "data": {
    "id": 2,
    "uuid": "3be1b711-c32f-47b2-8bde-b4415f37d600",
    "title": "Questionnaire",
    "htmlFilePath": "questionnaire.html",
    "reloadable": false,
    "active": true,
    "comments": "python client test"
  }
}
```

`htmlFilePath` 是相对 study 资产根目录的路径。HTML 中引用的 JS 和 CSS 使用相对路径时，会从组件运行路径解析到 study 资产。

### 生成 study code

`POST /studies/{id}/studyCodes` 同时承担查询和生成。PersonalMultiple 示例：

```bash
curl -sS \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"type":"PersonalMultiple","comment":"dev test"}' \
  "http://127.0.0.1:9000/jatos/api/v1/studies/1/studyCodes"
```

实际响应：

```json
{"apiVersion":"1.1.0","data":["okhubp6izDS"]}
```

`GET /studies/{id}/studyCodes` 已被标记为废弃，缺少 `type` 时返回 400 `VALIDATION_ERROR`。类型可选 `PersonalSingle`、`PersonalMultiple`、`GeneralSingle`、`GeneralMultiple`、`MTurk`，也接受 `ps`、`pm`、`gs`、`gm`、`mt` 缩写。

用 `GET /jatos/api/v1/studyCodes/{code}` 查询 PersonalMultiple 详情，实际返回：

```json
{
  "apiVersion": "1.1.0",
  "data": {
    "studyCode": "MupxWYgmuL7",
    "batchId": 2,
    "type": "PersonalMultiple",
    "comment": "python client",
    "active": true,
    "studyLinkPath": "/publix/MupxWYgmuL7",
    "studyEntryPath": "/publix/run?code=MupxWYgmuL7"
  }
}
```

GeneralMultiple 的同一查询在 3.11.3 返回 500：

```json
{"apiVersion":"1.1.0","error":{"code":"UNEXPECTED_ERROR","message":"Unexpected error"}}
```

日志中的决定性两行：

```text
java.lang.NullPointerException
    at utils.common.JsonUtils.getStudyLinkData(JsonUtils.java:571)
    at controllers.gui.Api.getStudyCode(Api.java:1118)
```

原因是 GeneralMultiple 的 `worker_id` 为 NULL。直接使用 `/publix/{studyCode}` 模板可以正常启动，不依赖这个查询接口。

### 批次允许的 worker 类型

API 创建的 study 自带一个默认批次，默认 `allowedWorkerTypes` 只有 `PersonalSingle` 和 `PersonalMultiple`。本次对新建 study 的批次实际查询结果：

```json
{"id":4,"allowedWorkerTypes":["PersonalSingle","PersonalMultiple"]}
```

使用 GeneralMultiple 链接前需要修改批次：

```bash
curl -sS -X PATCH \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"allowedWorkerTypes":["PersonalSingle","PersonalMultiple","GeneralMultiple"]}' \
  "http://127.0.0.1:9000/jatos/api/v1/batches/1"
```

实际响应中的关键字段：

```json
{"apiVersion":"1.1.0","data":{"id":1,"allowedWorkerTypes":["PersonalSingle","GeneralMultiple","PersonalMultiple"]}}
```

未加入允许列表的 worker 类型访问 publix 链接会得到 403。

## Publix 链接

| 用途 | 路径 |
| --- | --- |
| 直接运行 | `/publix/{studyCode}` |
| 确认页 | `/publix/run?code={studyCode}` |
| 组件启动页 | `/publix/{studyResultUuid}/{componentUuid}/start` |

`GET /publix/{studyCode}` 实际返回 `303 See Other`，`Location` 指向组件启动页，并设置 `PLAY_SESSION` 和 `JATOS_ID_<studyResultId>` cookie。本地实测时 `JATOS_ID_6` 对应的 `studyResultId=6`，`JATOS_ID_14` 对应 `studyResultId=14`，因此 cookie 名称后缀是 studyResultId。

`JATOS_ID_<studyResultId>` 的值包含以下字段：

```text
batchId
componentId
componentPos
componentResultId
creationTime
studyAssets
urlBasePath
jatosRun
studyId
studyResultId
studyResultUuid
workerId
workerType
```

`jatos.js` 会读取与当前 `studyResultUuid` 匹配的 cookie，并把所有字段复制到 `window.jatos`。PersonalMultiple 的 code 可重复运行，本次同一个 code 连续产生了多个 studyResult，workerId 保持为 6。

组件资产需要有效的 JATOS 运行 cookie。带 `JATOS_ID_<studyResultId>` cookie 请求组件资产返回 200，不带 cookie 返回 403。

JATOS 3.11.3 的 jatos.js 地址为 `/assets/javascripts/jatos.js`。实际请求结果：

```text
GET /jatos.js                         -> 404
GET /assets/javascripts/jatos.js      -> 200
```

HTML 组件中应使用可用的地址，例如：

```html
<script src="/assets/javascripts/jatos.js"></script>
```

## 结果 ID 与双写

### 浏览器侧字段

在组件中等待 `jatos.onLoad` 后再读取以下字段：

| 字段 | 含义 |
| --- | --- |
| `jatos.studyResultId` | JATOS study result 的数字 ID |
| `jatos.studyResultUuid` | source 中 study result 的 UUID，用于 publix 结果路径 |
| `jatos.componentResultId` | 当前组件的 component result 数字 ID |
| `jatos.componentId` | 当前组件 ID |
| `jatos.workerId` | worker ID |
| `jatos.workerType` | `PersonalMultiple`、`GeneralMultiple` 等 |
| `jatos.studyId` | study ID |
| `jatos.batchId` | 批次 ID |
| `jatos.componentList` | 组件列表，每项包含 `id`、`uuid`、`title` |

`studyResultUuid` 和 `componentResultId` 来自 cookie 与 URL；`componentUuid` 不在 cookie 的顶层字段中，可从 `jatos.componentList.find(c => c.id === jatos.componentId).uuid` 或启动页 URL 取得。以上字段来自 3.11.3 的 `jatos.js` 源码和实测 cookie。真实 Chrome 中的问卷组件已通过 Playwright 验证：`jatos.workerId`、`jatos.studyResultId`、`jatos.componentResultId` 均可读取，提交后 JATOS 结果与平台记录一一对应。

仓库中的问卷代码在 `frontend/src/questionnaire/jatos.ts` 中读取 `studyResultId`、`componentResultId`、`workerId`，并通过 `jatos.submitResultData` 写入 JATOS。答案同时提交给平台后，平台记录应保存 `jatosWorkerId`、`jatosStudyResultId`、`jatosComponentResultId` 三个字段，便于关联两套结果。

### 服务端查询结果

用 API token 查询某个 studyResult 的元数据：

```bash
curl -sS -X POST \
  -H "Authorization: Bearer $JATOS_API_TOKEN" \
  "http://127.0.0.1:9000/jatos/api/v1/results/metadata?download=false&studyResultId=15"
```

响应是包含 `data` 数组的对象，studyResult 在 `data[].studyResults[]` 中。本次实际查询结果的关键字段：

```json
[
  {
    "id": 15,
    "uuid": "030ffefb-34b4-4a48-bf92-69febdaa31ed",
    "studyCode": "MupxWYgmuL7",
    "workerId": 6,
    "workerType": "PersonalMultiple",
    "batchId": 2,
    "studyState": "STARTED",
    "componentResults": [
      {
        "id": 12,
        "componentUuid": "3be1b711-c32f-47b2-8bde-b4415f37d600",
        "componentState": "STARTED",
        "path": "/study_result_15/comp-result_12",
        "data": {"size": 27, "sizeHumanReadable": "27 B"}
      }
    ]
  }
]
```

响应还包含 `studyId`、`studyUuid`、`studyTitle`、`startDate`、`lastSeenDate`、`batchUuid`、`batchTitle`、`endDate`、`duration`、`isQuotaReached`，以及 componentResult 的 `componentId`、`startDate`、`endDate`、`duration`、`files`。`data[].studyResults[].id` 可用于后续查询。

### 直接提交结果数据

`jatos.submitResultData` 最终调用：

```text
PUT /publix/{studyResultUuid}/{componentUuid}/resultData
Content-Type: text/plain
```

服务端使用 `request.body().asText()` 读取请求体，使用 `application/json` 会得到 `Result data empty`。本次 curl 流程为：`GET /publix/{studyCode}` 取得 303 和 cookie，带 cookie 请求一次 `/start`，再用 cookie 提交：

```bash
curl -sS -X PUT \
  -b "$COOKIE_JAR" \
  -H 'Content-Type: text/plain' \
  --data '{"probe":2,"source":"curl"}' \
  "http://127.0.0.1:9000/publix/$STUDY_RESULT_UUID/$COMPONENT_UUID/resultData"
```

实际返回 HTTP `200`，响应体为空；随后 metadata 中 `componentState` 为 `STARTED`，`data.size` 为 27。组件结果必须处于当前可写状态。若在组件已经结束后再次启动，再向旧的 component result 提交，会返回 403：

```text
Impossible to put result data to component result
```

组件中应使用 `jatos.submitResultData(data, onSuccess, onError)`，由 jatos.js 维护组件运行状态，不要从浏览器直接调用 publix 的 PUT 路径。

`JATOS_API_TOKEN` 只能保存在平台服务端，禁止放进问卷 HTML 或浏览器环境变量。

## 受保护答案的数据流与 JATOS 原始结果边界

受保护题型为 `real_name`、`alipay_phone`、`identity_document`。每份 Room 问卷必须各包含一道，题目始终必填。题目 ID 由问卷 schema 决定，平台在问卷上下文中返回 `protectedQuestionIds`。

提交一次问卷的数据流：

1. 问卷组件在浏览器中收集全部答案。
2. 组件先调用 `jatos.submitResultData`，提交对象中的 `answers` 包含受保护答案。JATOS component result 因此保存一份原始答案。
3. 组件随后把相同答案和 `jatosWorkerId`、`jatosStudyResultId`、`jatosComponentResultId` 发送到平台 `POST /api/jatos/questionnaire/complete`。
4. 平台按 schema 拆分受保护答案，校验三种题型各一道、必填且格式有效，再从写入 `questionnaire_responses.answers_json` 的答案对象中删除受保护题目。
5. 平台使用 `IDENTITY_ENCRYPTION_KEY` 加密真实姓名、支付宝手机号和证件号码，按 Room 与参与者写入 `participant_identities`。证件类型明文保存。
6. 草稿在组件侧和平台侧都不包含受保护答案。问卷上下文回显、Room 事件、`export.json`、分析 ZIP 和分析导出的问卷副本也不包含受保护答案。
7. 支付名单和报销清单在服务端解密身份记录后生成，只返回给管理员并写入审计日志。

JATOS 原始结果边界：平台只控制自身保存的数据和导出。JATOS 数据库、组件结果、study 导出和 JATOS 备份可能保留受保护答案的原文，平台不能删除或改写这些记录。JATOS 管理员权限、数据库访问、备份和离线副本必须按个人信息标准单独保护。`IDENTITY_ENCRYPTION_KEY` 只保护平台侧 `participant_identities`，不能解密或清理 JATOS 原始结果。需要删除 JATOS 原始结果时，按 JATOS 的结果管理功能单独执行。

## 上传平台问卷组件

问卷组件是 `frontend/src/questionnaire/` 的 Vite 构建产物，入口为 `frontend/dist-questionnaire/questionnaire.html`，静态文件在 `assets/` 下，使用相对路径引用。

构建：

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo/moyo-online-exp/frontend
npm install
npm run build
```

`frontend/questionnaire.html` 使用 `/assets/javascripts/jatos.js` 加载 JATOS 脚本，这是 3.11.3 的静态路由。`vite.questionnaire.config.ts` 设置 `base: "./"`，避免构建资源与 JATOS 自带的 `/assets/` 路由冲突。

### 自动创建 study 与组件

`scripts/deploy_jatos_questionnaire.py` 完成以下操作：

1. 创建 study（或使用 `--study` 指定的已有 study）。
2. 把默认批次的 `allowedWorkerTypes` 更新为包含 `GeneralMultiple`。
3. 上传 `frontend/dist-questionnaire` 下的全部文件，保留 `assets/` 相对路径。
4. 创建 HTML 组件，`htmlFilePath` 为 `questionnaire.html`。
5. 生成 GeneralMultiple study code，并输出 JSON。

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo/moyo-online-exp
set -a
. .review/jatos/api_token.env
set +a
export JATOS_BASE_URL=http://127.0.0.1:9000
uv run --with httpx python scripts/deploy_jatos_questionnaire.py --title "Moyo 后测问卷"
```

输出中的 `studyCode` 填入平台环境变量 `JATOS_STUDY_CODE` 或管理端设置。GeneralMultiple study code 的 `amount` 上限为 1000；同一链接可在额度内重复运行。

### 平台地址与 CORS

问卷通过构建时注入的 `VITE_PLATFORM_BASE_URL` 获取平台地址。生产镜像在构建时把 `PUBLIC_BASE_URL` 注入为 `VITE_PLATFORM_BASE_URL`，并忽略 URL 中的 `base` 查询参数。

本地测试需要构建问卷组件时显式启用覆盖：

```bash
VITE_ALLOW_BASE_OVERRIDE=true npm --prefix frontend run build
```

启用后才可以在组件 URL 追加 `base`：

```text
http://127.0.0.1:9000/publix/<studyCode>?rt=<token>&pid=<analysisCode>&base=http%3A%2F%2F127.0.0.1%3A8000
```

可以设置 `VITE_ALLOWED_PLATFORM_ORIGINS=https://a.example,https://b.example` 限制允许的覆盖来源。`tests/integration/test_jatos.py` 构建问卷组件时会自动启用覆盖。

平台 CORS 允许 `PUBLIC_BASE_URL` 和 `JATOS_BASE_URL` 的 origin，`/api/jatos/*` 的 GET 与 POST 可用。问卷组件在两个 origin 之间使用 fetch，不依赖参与者 cookie。

### 真实 JATOS 自动化测试

`tests/integration/test_jatos.py` 会：

- 通过 JATOS API 创建独立 study，启用 GeneralMultiple，上传当前构建产物。
- 启动真实 uvicorn 和 MariaDB 测试库，完成两名参与者的对局直到问卷阶段。
- 用 Playwright 打开真实 JATOS 链接，提交问卷并等待跳回平台。
- 校验 JATOS result 中的答案与平台响应中的 `jatosStudyResultId`、`jatosComponentResultId` 完全对应。
- 校验平台 Room 归档为 `completed`，付款记录生成。

运行：

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo/moyo-online-exp
uv run pytest tests/integration/test_jatos.py -q
```

测试读取 `TEST_JATOS_API_TOKEN`，或 `.review/jatos/api_token.env`。需要在 PATH 中存在 Google Chrome；Playwright 使用 `PLAYWRIGHT_CHANNEL`（默认 `chrome`）。

## 清理

测试结束后先停止服务：

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo/.review/jatos/jatos_mac_aarch64_java
./loader.sh stop
```

```bash
/opt/homebrew/opt/mariadb@10.11/bin/mariadb-admin \
  --protocol=TCP -h 127.0.0.1 -P 3307 -u root shutdown
```

确认 9000 和 3307 端口没有监听进程后，删除本地运行目录：

```bash
cd /Users/mpxuann/Documents/research/projects/26-Moyo
rm -rf .review/jatos
rm -rf .review/mariadb-data .review/mariadb-run .review/mariadb-server.log
```

`.review/jatos` 包含安装文件、令牌和测试资产，`.review/mariadb-data` 包含测试数据库。两者都在 `moyo-online-exp/` 仓库之外，不提交到 git。重跑 `scripts/jatos_dev_setup.sh` 会重新创建这些内容。

## JATOS 3.11.3 与 3.12.0 的已知差异

以下内容来自 JATOS 3.12.0 的官方发布说明，未在本机安装 3.12.0 验证。

| 项目 | 3.11.3 | 3.12.0 |
| --- | --- | --- |
| Java | Java 11，内置 Temurin 11.0.29 | Java 21 及以上，内置 Java 25 |
| 默认嵌入式数据库 | H2 1.4.197 | H2 2.4，旧 H2 文件需要导出再导入 |
| 外部数据库 | MySQL Connector/J 8.0.28，支持 MariaDB | MariaDB 和 MySQL 不需要 H2 转换 |
| API 兼容性 | `/jatos/api/v1` | 官方说明现有 study、导入导出和 API 响应向后兼容 |
| 管理员密码 | 默认 `admin` / `admin` | 支持通过 `jatos.conf` 或环境变量设置管理员密码 |
| jatos.js | 单个构建，依赖 jQuery | 重构并新增不依赖 jQuery 的 slim 构建 |
| 发布状态 | 稳定版 | 发布说明中标记为 pre-release |

3.12.0 发布说明只写了“通过 jatos.conf / 环境变量设置 admin 密码”，没有给出配置项名称；本机也未验证 3.12.0，不能据此推断配置项名称。升级前应从 3.12 文档获取准确配置项名称，并在 MariaDB 环境下验证 jatos.js 的加载路径与 slim 构建兼容性。本项目的 MariaDB 部署不需要处理 H2 迁移。

## 已知问题与限制

- JATOS 3.11.3 的 `GET /jatos/api/v1/studyCodes/{code}` 对 GeneralMultiple 返回 500，PersonalMultiple 正常。直接使用 `/publix/{studyCode}` 链接可以绕开这个查询。
- `/jatos.js` 在 3.11.3 返回 404，应加载 `/assets/javascripts/jatos.js`。
- API 创建的 study 默认批次只允许 `PersonalSingle` 和 `PersonalMultiple`；使用 GeneralMultiple 前需要 PATCH 批次。
- 管理员初始密码为默认的 `admin`，日志中没有随机初始密码。
- `PUT .../resultData` 必须使用 `text/plain`，并且组件结果必须处于可写状态。
- 真实问卷构建产物、平台后端 CORS 和浏览器中的 `window.jatos` 字段已经由 `tests/integration/test_jatos.py` 验证。JATOS 3.12.0 安装和 slim 构建未在本机验证。
- `scripts/jatos_dev_setup.sh` 管理的是端口 3307、数据目录 `.review/mariadb-data` 的本地 MariaDB 实例，不会修改 Homebrew 服务或其他端口上的 MariaDB。

## 参考

- JATOS 3.12.0 发布说明：https://github.com/JATOS/JATOS/releases/tag/v3.12.0
- JATOS 安装文档：https://www.jatos.org/Installation.html
- JATOS 配置文档：https://www.jatos.org/JATOS_Configuration
