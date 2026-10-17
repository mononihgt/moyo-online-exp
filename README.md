# Canvas 双人在线游戏 v3（公网部署版）

这是一个基于 FastAPI + WebSocket 的双人在线游戏。浏览器连接到同一个公开地址，以 6×6 棋盘进行 7 个 trial 的对局：trial 0 为练习，trial 1 到 6 为正式 trial。地图条件由主试通过 `MAP_CONDITION` 环境变量分配，参与者界面不显示条件编号。

## 当前版本特性

- 一个服务实例固定运行一个地图条件，支持 6 种参考布局和独立的 `asym` 水平。
- 固定 7 个 trial：1 个练习 trial 加 6 个正式 trial，每个 trial 20 回合，每回合 30 秒。
- 正式 trial 的初始兵力顺序在房间创建时随机打乱，随机种子和顺序写入记录。
- 数据格式升级为 `schemaVersion = 3`，ZIP 内按 `trial0.csv` 到 `trial6.csv` 导出。
- 浏览器在 HTTPS 页面下自动使用 `wss://`，在 HTTP 页面下使用 `ws://`。
- 服务端支持云平台通过 `PORT` 环境变量分配端口，并启用反向代理头。
- `/healthz` 健康检查接口返回当前条件信息。
- WebSocket ping/pong 减少公网空闲断线；服务必须以单 worker 运行。

## 本地运行

```bash
python -m pip install -r requirements.txt
MAP_CONDITION=ref0 uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

打开 `http://127.0.0.1:8000`。局域网内其他设备可打开：

```text
http://你的局域网IP:8000
```

两名玩家都点击 `start matching` 后即可匹配，不需要输入总局数或地图条件。未设置 `MAP_CONDITION` 时默认为 `ref0`。

## 地图条件

服务端在启动时读取环境变量 `MAP_CONDITION`：

```text
MAP_CONDITION
```

允许值为：

```text
ref0, ref1, ref2, ref3, ref4, ref5, asym
```

默认值为 `ref0`，对应参考 `server.py` 的 `showBound = 0`。无效取值会让应用在启动时直接抛出 `ValueError`。

一个服务实例只运行一个地图条件。需要同时运行多个条件时，启动多个实例，分别设置不同的 `MAP_CONDITION` 和端口。匹配只按 6×6 棋盘进行，不在客户端区分条件。参与者界面不显示条件编号、`showBound` 或条件选择控件，条件分配对参与者保持盲态。主试可以通过 `/healthz` 返回的 `mapCondition`、`showBound`、`isReferenceCondition` 核对当前实例。

示例：

```bash
MAP_CONDITION=ref3 uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### 条件与字段映射

| `MAP_CONDITION` | 参考 `showBound` | 玩家画面 | `isBoundary` | `isConsistent` | `dev` | `isReferenceCondition` |
|---|---|---|---|---|---|---|
| `ref0` | 0 | 左 3 列蓝色，右 3 列红色 | 1 | 0 | 0 | true |
| `ref1` | 1 | 左 3 列红色，右 3 列蓝色 | 1 | 1 | 0 | true |
| `ref2` | 2 | 全部蓝色 | 0 | 2 | 0 | true |
| `ref3` | 3 | 全部红色 | 0 | 3 | 0 | true |
| `ref4` | 4 | 上半红色，下半蓝色 | 1 | 4 | 0 | true |
| `ref5` | 5 | 上半蓝色，下半红色 | 1 | 5 | 0 | true |
| `asym` | null | 玩家 1 看到 `ref0`；玩家 2 看到全部红色 | 2 | 6 | 0 | false |

六种参考条件来自 `reference/warGame2DSp/src/initialize.py` 的布局和字段映射，`isBoundary`、`isConsistent`、`dev` 与参考实现一致，`showBound` 为 0 到 5。

`asym` 是独立水平，复现原在线 `boards = 4` 的行为：玩家 1 的颜色矩阵为 `ref0`，玩家 2 的颜色矩阵为全部红色。`asym` 的 `isBoundary = 2`、`isConsistent = 6`、`showBound = null`、`isReferenceCondition = false`。分析时必须单独处理，不能与 `isBoundary = 0` 或 `isBoundary = 1` 的参考条件合并。

`mapColor1` 和 `mapColor2` 记录两名玩家实际看到的 6×6 颜色矩阵，`mapColor` 写入玩家 1 的矩阵。`isBoundary1`、`isBoundary2` 按各自颜色矩阵计算。地图条件只改变颜色，共享的 shapes、numbers 和战斗计算保持不变。

数据行中的 `boards` 仅作为旧字段保留，取值为：`ref0` 为 3、`ref1` 为 null、`ref2` 为 1、`ref3` 为 2、`ref4` 为 null、`ref5` 为 null、`asym` 为 4。条件判断使用 `conditionId` 和 `isReferenceCondition`。

## 最简单的公网部署：Render

1. 将本目录上传到 GitHub 仓库。
2. 登录 Render，选择 **New > Blueprint**，连接该仓库。
3. Render 会读取根目录下的 `render.yaml` 和 `Dockerfile`。
4. 部署完成后，将 Render 给出的 `https://...onrender.com` 地址发给两位玩家。
5. 两人打开同一个地址，点击 `start matching`。未设置 `MAP_CONDITION` 时实例运行 `ref0`；其他条件需要在 Render 的环境变量中添加 `MAP_CONDITION`。
6. 需要同时运行多个条件时，为每个条件部署一个独立实例，并保证同一房间的两名玩家连接到同一实例。

Render 免费实例可能休眠，首次打开时启动会较慢；正式长期运行建议使用非休眠实例。

## 使用 Docker 部署

```bash
docker build -t canvas-duel-game .
docker run --rm -p 8000:8000 -e PORT=8000 -e MAP_CONDITION=ref0 canvas-duel-game
```

访问 `http://服务器IP:8000`。正式公网环境建议在前面放置带 TLS 证书的 Nginx 或 Caddy，并通过域名使用 HTTPS。

启动容器时可限制允许的域名：

```bash
docker run --rm -p 8000:8000 \
  -e PORT=8000 \
  -e MAP_CONDITION=ref3 \
  -e ALLOWED_HOSTS=game.example.com \
  canvas-duel-game
```

## Nginx 反向代理示例

```nginx
server {
    listen 443 ssl http2;
    server_name game.example.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

## 重要架构限制

当前匹配队列、房间状态和棋局状态均保存在 Python 进程内存中，因此：

- 必须使用 `--workers 1`。
- 云平台实例数必须保持为 1，不能水平扩容。
- 服务重启会中断正在进行的游戏。
- 两名玩家必须连接到同一个实例。
- 同一实例只运行一个 `MAP_CONDITION`；不同条件的参与者必须连接到各自条件的实例。
- 棋盘固定为 6×6。

若后续需要多实例、高可用或大量玩家，应将匹配与房间状态迁移到 Redis，并使用 Redis Pub/Sub 或其他消息系统同步 WebSocket 节点。

## 游戏机制函数

位于 `app/game_logic.py`：

- `MAP_CONDITIONS` 和 `get_condition_metadata(...)`：7 个地图条件的布局与字段映射。
- `get_condition_colors(...)`：按条件与玩家编号返回 6×6 颜色矩阵。
- `build_trial_plan(seed)`：返回 7 个 trial 的随机计划。
- `create_initial_state(...)`：按 trial 计划中的初始兵力创建共享状态。
- `play_turn(...)`：返回回合后的状态与本回合机制字段（政策、战果、伤亡、补给、交火位置）。
- `calculate_turn(...)`：`play_turn` 的兼容包装，只返回回合后的状态。
- `complete_game_to_turn_20(...)`：一方领地归零后，按参考实现补算到第 20 回合。
- `determine_winner(...)`：根据最终领地判定获胜方。
- `get_flashing_cells(...)`：决定本回合结算后闪烁 1 秒的坐标。
- `get_player_view(...)`：根据条件和玩家编号生成玩家实际看到的颜色视图。

## Trial 结构

- 每个房间固定 7 个 trial：`TOTAL_TRIALS = 7`、`PRACTICE_TRIALS = 1`、`FORMAL_TRIALS = 6`。
- `trial = 0` 是练习 trial，`trial = 1` 到 6 是正式 trial。
- 每个 trial 20 回合，每回合 30 秒。
- `game` 为 1 到 7，保持旧数据结构和界面兼容；`formalTrial` 在练习 trial 为 0，在正式 trial 为 1 到 6。
- 练习 trial 固定使用兵力索引 0，即 A7、B7。
- 正式 trial 使用兵力索引 1 到 6，六组初始兵力为 A7/B7、A8/B8、A8/B9、A7/B8、A9/B8、A8/B7。
- 每个房间生成一个 64 位随机种子 `trialPlanSeed`，用 `random.Random(seed)` 打乱 `[1, 2, 3, 4, 5, 6]`，得到 `trialOrder = [0] + shuffled`。
- 每个 trial 的 `sourceIndex`、`soldierFromBaseA`、`soldierFromBaseB` 写入记录。
- 练习 trial 和正式 trial 都写入数据。练习 trial 的 `isPractice = 1`，正式 trial 的 `isPractice = 0`。正式绩效分析排除练习 trial。
- 在线服务在练习 trial 中保留“超时补选一个随机格子”的保护，避免房间因为无人提交而永久挂起。参考客户端在 trial 0 不自动补选，这是本次保留的在线差异。

## 游戏流程

- 双方都提交至少一个格子后结算；空选择会被服务端拒绝，不会锁定回合。
- 提交消息包含 `game` 与 `turn`；不属于当前回合的延迟提交会被忽略。
- 超时方由服务器随机补选一个格子，并记录 `selectionSource = timeout`。该保护在练习 trial 中同样生效。
- 一方领地归零后，服务端补算剩余回合，每个 trial 固定记录 21 行（round 0 到 round 20）。
- 回合结果发送后，指定格子闪烁 1 秒。
- 前 6 个 trial 结束后进入休息界面，双方按 `Ready for Next Trial` 后进入下一 trial；最长 60 秒，超时自动继续。
- 练习 trial 的休息界面提示该 trial 不计入正式绩效。
- 最后一个正式 trial 结束后显示 `All formal trials completed` 与 JSON、合并 CSV、分析数据 ZIP 下载链接。

## 数据格式与分析

### 下载接口

- `GET /data/{roomId}.json`：完整 JSON 记录。
- `GET /data/{roomId}.csv`：包含所有 trial 的合并 CSV。
- `GET /data/{roomId}.zip`：每个 trial 一个 CSV，供参考分析脚本逐 trial 读取。
- `GET /data`：记录列表，每项包含 `jsonUrl`、`csvUrl`、`zipUrl`。

游戏结束消息和结束面板都包含 ZIP 下载地址。旧记录的 `schemaVersion` 不等于 3 时，CSV 与 ZIP 分析导出返回 409；JSON 仍然可以下载。

### JSON

顶层字段为 `schemaVersion = 3`、`roomId`、`createdAt`、`completedAt`、`rows`、`cols`、`boards`、`totalGames`、`experiment`、`condition`、`trialPlan`、`players`、`games`、`turns`。其中 `boards` 和 `totalGames` 为兼容旧结构保留的字段。

- `experiment`：`totalTrials = 7`、`practiceTrials = 1`、`formalTrials = 6`、`trialPlanSeed`、`trialOrder`、`mapCondition`。
- `condition`：`conditionId`、`showBound`、`isReferenceCondition`、`isBoundary`、`isConsistent`、`dev`、`legacyBoards`、`mapColor`、`mapColor1`、`mapColor2`、`isBoundary1`、`isBoundary2`。
- `trialPlan`：每个 trial 一项，包含 `trial`、`game`、`isPractice`、`formalTrial`、`sourceIndex`、`soldierFromBaseA`、`soldierFromBaseB`。
- `games`：每个 trial 一条总结，包含获胜方、结束原因、结束回合、补算回合数、当局初始兵力，以及 `trial`、`isPractice`、`formalTrial`、`sourceIndex`、`conditionId`、`showBound`、`isReferenceCondition`。
- `turns`：所有 trial 的扁平行列表。每个 trial 21 行：round 0 是初始状态，round 1 到 20 是回合记录。合并 CSV 共 147 行（7 × 21）。
- 每行包含参考 19 字段、房间与 trial 编号、双方选择、结算前后数字矩阵、选择来源、自动补选标记、补算标记，以及回填到每一行的 `endReason` 和 `winner`。
- 每行新增 `trial`、`isPractice`、`formalTrial`、`sourceIndex`、`conditionId`、`showBound`、`isReferenceCondition`。旧字段 `boards`、`mapColor`、`mapColor1`、`mapColor2`、`isBoundary1`、`isBoundary2` 仍保留。

结束原因 `endReason` 为 `annihilation`（领地归零）或 `turn_limit`（达到第 20 回合）。`annihilation` 时获胜方为仍有领地的一方；`turn_limit` 时 `winner` 为 `null`。选择来源 `selectionSource1/2` 为 `manual`、`timeout`、`forced` 或初始行的 `initial`。

### CSV

前 19 列与参考 `server.py` 完全一致：

```text
soldierPolicyA,soldierPolicyB,posListA,posListB,warField,soldiers,mapSize,
isBoundary,soldierFromBaseA,soldierFromBaseB,mapColor,dev,isConsistent,numOfWar,
warLostA,warLostB,logisticsA,logisticsB,warLocation
```

之后追加在线实验字段，包括 `game`、`round`、`roomId`、双方选择索引与坐标、结算前后数字矩阵、选择来源、自动补选标记、补算标记、结束原因、获胜方、当局增援值、`boards`、玩家颜色矩阵与边界标记，以及 `trial`、`isPractice`、`formalTrial`、`sourceIndex`、`conditionId`、`showBound`、`isReferenceCondition`。

- 在 `asym` 下 `isBoundary` 写 2，`isConsistent` 写 6。六种参考条件的 `isBoundary` 写 0 或 1，`isConsistent` 写 0 到 5。
- 列表字段写成 Python 字面量，例如 `[1, 0, 2]`、`[[1, 2], [2, 1]]`，`ast.literal_eval` 可以直接解析。
- 文件使用 UTF-8 编码并带 BOM。
- 合并 CSV 按 `game`（即 `trial + 1`）与 `round` 排序；每个 trial 固定 21 行。

### ZIP

- ZIP 内每个 trial 一个文件，文件名为 `{roomId}-trial0.csv` 到 `{roomId}-trial6.csv`。
- 练习 trial 的文件保留，供核对数据。
- 正式分析必须排除 `trial0.csv`，或者读取后按 `isPractice = 1` 过滤，也可以保留 `formalTrial >= 1` 的行。

### 在参考 ANOVA.py 中使用

参考脚本 `reference/warGame2DSp/exc/ANOVA.py` 从 `reference/warGame2DSp/data` 目录读取 CSV（脚本把 `exc` 的上一级目录与 `data` 拼接）。将 ZIP 解压到该目录：

```bash
unzip game-<roomId>.zip -d ../reference/warGame2DSp/data
cd ../reference/warGame2DSp/exc
python ANOVA.py
```

`ANOVA.py` 不读取在线新增的 `isPractice` 字段，默认会把目录中的每个 CSV 都当成一个 trial。运行前必须从数据目录移除 `*-trial0.csv` 练习文件，或者在读取 CSV 后自行过滤 `isPractice = 1` 的行。

`ANOVA.py` 通过文件名倒数第 5 个字符读取 trial 编号，`trial0.csv` 到 `trial9.csv` 都能被这一规则解析。练习 `trial0.csv` 必须排除。若以后单个房间超过 10 个 trial，ZIP 仍会导出全部文件，原始脚本无法正确区分 `trial10.csv` 及之后的编号，需要先修改分析读取方式。

`ANOVA.py` 用文件名和文件顺序生成 `participantsPair`，并且会读取数据目录中的全部 CSV。一次只放一个房间的文件，或者先按每行已有的 `roomId` 字段分组再分析。多个房间的 ZIP 同时解压到同一目录时，原始脚本的 `participantsPair` 分组会混淆。

运行参考脚本需要它原有环境中的 `pandas`、`scipy`、`statsmodels`、`researchpy`、`pymer4`、`mne`、`matplotlib`、`seaborn`。在线服务的 `requirements.txt` 不包含这些分析依赖。

`reference/warGame2DSp/exc/warWithVariance.py` 和 `trialWithVariance.py` 额外需要 `arrangementA/B` 防守线编排数据。在线客户端没有防守线输入，ZIP 与合并 CSV 不包含这些字段，因此这两个脚本不能直接使用。`ANOVA.py` 使用 19 个参考字段，是本次兼容目标。

## 未修复的已知限制

本次未修复数据持久化、下载鉴权与连接稳定性：Render 免费实例的本地文件系统在重启或重新部署后会丢失记录，`/data` 与下载接口没有鉴权，对手离开仍会覆盖结束面板，匹配队列也不会清理失效连接。正式实验若要求长期保存，需要改为外部数据库或对象存储（例如 PostgreSQL、Supabase 或 S3）。
