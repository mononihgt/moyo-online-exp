#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$REPO_DIR/.." && pwd)"

JATOS_VERSION="3.11.3"
JATOS_ARCHIVE="jatos_mac_aarch64_java.zip"
JATOS_DOWNLOAD_URL="https://github.com/JATOS/JATOS/releases/download/v${JATOS_VERSION}/${JATOS_ARCHIVE}"
JATOS_ROOT="${JATOS_ROOT:-$PROJECT_ROOT/.review/jatos}"
JATOS_CACHE_DIR="${JATOS_CACHE_DIR:-$PROJECT_ROOT/.cache/jatos}"
JATOS_HOME="${JATOS_HOME:-$JATOS_ROOT/jatos_mac_aarch64_java}"
JATOS_PORT="${JATOS_PORT:-9000}"
JATOS_DB_PORT="${JATOS_DB_PORT:-3307}"
JATOS_DB_NAME="${JATOS_DB_NAME:-jatos}"
JATOS_DB_USER="${JATOS_DB_USER:-jatos}"
JATOS_ADMIN_USER="${JATOS_ADMIN_USER:-admin}"
JATOS_ADMIN_PASSWORD="${JATOS_ADMIN_PASSWORD:-admin}"
MARIADB_ROOT_USER="${MARIADB_ROOT_USER:-root}"
MARIADB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-}"
MARIADB_DATA_DIR="${MARIADB_DATA_DIR:-$PROJECT_ROOT/.review/mariadb-data}"
MARIADB_RUN_DIR="${MARIADB_RUN_DIR:-$PROJECT_ROOT/.review/mariadb-run}"
MARIADB_LOG="${MARIADB_LOG:-$PROJECT_ROOT/.review/mariadb-server.log}"
BASE_URL="http://127.0.0.1:${JATOS_PORT}"
ZIP_PATH="$JATOS_CACHE_DIR/$JATOS_ARCHIVE"
DB_ENV_FILE="$JATOS_ROOT/jatos_db.env"
TOKEN_ENV_FILE="$JATOS_ROOT/api_token.env"
COOKIE_JAR="$JATOS_ROOT/.admin-cookies.txt"

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

jatos_healthy() {
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$BASE_URL/ping" || true)"
    [ "$code" = "200" ]
}

find_mariadb() {
    if ! BREW_PREFIX="$(brew --prefix mariadb@10.11 2>/dev/null)"; then
        if ! BREW_PREFIX="$(brew --prefix mariadb 2>/dev/null)"; then
            fail "未找到 MariaDB，请先执行：brew install mariadb@10.11"
        fi
    fi
    MARIADB="$BREW_PREFIX/bin/mariadb"
    MARIADB_ADMIN="$BREW_PREFIX/bin/mariadb-admin"
    MARIADBD="$BREW_PREFIX/bin/mariadbd"
    MARIADB_INSTALL_DB="$BREW_PREFIX/bin/mariadb-install-db"
    for binary in "$MARIADB" "$MARIADB_ADMIN" "$MARIADBD" "$MARIADB_INSTALL_DB"; do
        [ -x "$binary" ] || fail "缺少可执行文件：$binary"
    done
}

root_args=()
build_root_args() {
    root_args=(--protocol=TCP -h 127.0.0.1 -P "$JATOS_DB_PORT" -u "$MARIADB_ROOT_USER")
}

mariadb_alive() {
    MYSQL_PWD="$MARIADB_ROOT_PASSWORD" "$MARIADB_ADMIN" "${root_args[@]}" ping >/dev/null 2>&1
}

ensure_mariadb() {
    mkdir -p "$MARIADB_DATA_DIR" "$MARIADB_RUN_DIR"
    if mariadb_alive; then
        log "MariaDB 已在 127.0.0.1:${JATOS_DB_PORT} 运行"
        return
    fi
    if [ ! -d "$MARIADB_DATA_DIR/mysql" ]; then
        log "初始化 MariaDB 数据目录 $MARIADB_DATA_DIR"
        "$MARIADB_INSTALL_DB" \
            --basedir="$BREW_PREFIX" \
            --datadir="$MARIADB_DATA_DIR" \
            --auth-root-authentication-method=normal \
            --skip-test-db
    fi
    if lsof -nP -iTCP:"$JATOS_DB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        fail "端口 ${JATOS_DB_PORT} 已被占用，但 MariaDB root 认证失败。请设置 MARIADB_ROOT_USER/MARIADB_ROOT_PASSWORD。"
    fi
    log "启动 MariaDB（127.0.0.1:${JATOS_DB_PORT}）"
    nohup "$MARIADBD" \
        --basedir="$BREW_PREFIX" \
        --datadir="$MARIADB_DATA_DIR" \
        --port="$JATOS_DB_PORT" \
        --bind-address=127.0.0.1 \
        --socket="$MARIADB_RUN_DIR/mysql.sock" \
        --pid-file="$MARIADB_RUN_DIR/mysql.pid" \
        --log-error="$MARIADB_LOG" \
        >/dev/null 2>&1 &
    local attempt
    for attempt in $(seq 1 60); do
        mariadb_alive && return
        sleep 1
    done
    tail -n 20 "$MARIADB_LOG" >&2 || true
    fail "MariaDB 未能在 60 秒内启动"
}

load_db_password() {
    if [ -n "${JATOS_DB_PASSWORD:-}" ]; then
        (umask 077; printf 'JATOS_DB_PASSWORD=%s\n' "$JATOS_DB_PASSWORD" > "$DB_ENV_FILE")
        chmod 600 "$DB_ENV_FILE"
    elif [ ! -s "$DB_ENV_FILE" ]; then
        (umask 077; printf 'JATOS_DB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > "$DB_ENV_FILE")
        chmod 600 "$DB_ENV_FILE"
    fi
    # shellcheck disable=SC1090
    . "$DB_ENV_FILE"
    [ -n "${JATOS_DB_PASSWORD:-}" ] || fail "无法从 $DB_ENV_FILE 读取 JATOS_DB_PASSWORD"
}

ensure_database() {
    MYSQL_PWD="$MARIADB_ROOT_PASSWORD" "$MARIADB" "${root_args[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS \`${JATOS_DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${JATOS_DB_USER}'@'127.0.0.1' IDENTIFIED BY '${JATOS_DB_PASSWORD}';
ALTER USER '${JATOS_DB_USER}'@'127.0.0.1' IDENTIFIED BY '${JATOS_DB_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${JATOS_DB_NAME}\`.* TO '${JATOS_DB_USER}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
    MYSQL_PWD="$JATOS_DB_PASSWORD" "$MARIADB" --protocol=TCP -h 127.0.0.1 -P "$JATOS_DB_PORT" \
        -u "$JATOS_DB_USER" -e "SELECT 1" "$JATOS_DB_NAME" >/dev/null
    log "数据库 ${JATOS_DB_NAME} 与用户 ${JATOS_DB_USER}@127.0.0.1 已就绪"
}

download_archive() {
    if [ -f "$ZIP_PATH" ] && unzip -t "$ZIP_PATH" >/dev/null 2>&1; then
        log "复用已下载的 JATOS 安装包"
        return
    fi
    mkdir -p "$JATOS_CACHE_DIR"
    [ -f "$ZIP_PATH" ] || : > "$ZIP_PATH"
    log "下载 JATOS ${JATOS_VERSION} 到缓存目录 $JATOS_CACHE_DIR（支持断点续传）"
    local attempt=0 before after stalled=0
    while [ "$attempt" -lt 40 ]; do
        attempt=$((attempt + 1))
        before="$(wc -c < "$ZIP_PATH")"
        if ! curl -fL -C - --connect-timeout 30 --max-time 300 -o "$ZIP_PATH" "$JATOS_DOWNLOAD_URL"; then
            log "传输中断，续传（第 ${attempt} 次）"
        fi
        after="$(wc -c < "$ZIP_PATH")"
        if unzip -t "$ZIP_PATH" >/dev/null 2>&1; then
            log "JATOS 安装包校验通过"
            return
        fi
        if [ "$after" -le "$before" ]; then
            stalled=$((stalled + 1))
            [ "$stalled" -ge 3 ] && fail "下载连续 3 次无进展，请检查网络后重新执行"
        else
            stalled=0
        fi
        sleep 2
    done
    fail "下载 JATOS 安装包失败"
}

install_jatos() {
    if [ -f "$JATOS_HOME/VERSION" ] && [ "$(cat "$JATOS_HOME/VERSION")" = "$JATOS_VERSION" ]; then
        log "复用已安装的 JATOS ${JATOS_VERSION}"
        return
    fi
    download_archive
    log "解压 JATOS 到 $JATOS_ROOT"
    unzip -oq "$ZIP_PATH" -d "$JATOS_ROOT"
    [ -f "$JATOS_HOME/VERSION" ] || fail "安装包解压后缺少 VERSION 文件"
    [ "$(cat "$JATOS_HOME/VERSION")" = "$JATOS_VERSION" ] || fail "解压后的 JATOS 版本不是 ${JATOS_VERSION}"
    chmod u+x "$JATOS_HOME/loader.sh"
}

write_jatos_conf() {
    mkdir -p "$JATOS_HOME/conf"
    cat > "$JATOS_HOME/conf/jatos.conf" <<'CONF'
# Managed by scripts/jatos_dev_setup.sh
include "application.conf"

jatos.http.address = "127.0.0.1"
jatos.http.port = ${?JATOS_HTTP_PORT}

jatos.db.url = ${?JATOS_DB_URL}
jatos.db.driver = ${?JATOS_DB_DRIVER}
jatos.db.username = ${?JATOS_DB_USERNAME}
jatos.db.password = ${?JATOS_DB_PASSWORD}

# API 生成的 token 默认 1 小时，本地开发放宽到 1 天
jatos.api.tokens.apiGeneration.expiresAfter = 86400
CONF
}

export_jatos_env() {
    mkdir -p "$JATOS_ROOT/tmp"
    export JATOS_HTTP_ADDRESS="127.0.0.1"
    export JATOS_HTTP_PORT="$JATOS_PORT"
    export JATOS_DB_DRIVER="com.mysql.cj.jdbc.Driver"
    export JATOS_DB_USERNAME="$JATOS_DB_USER"
    export JATOS_DB_PASSWORD
    export JATOS_DB_URL="jdbc:mysql://127.0.0.1:${JATOS_DB_PORT}/${JATOS_DB_NAME}?useUnicode=true&characterEncoding=UTF-8&serverTimezone=UTC&useSSL=false&allowPublicKeyRetrieval=true"
    export JATOS_TMP_PATH="$JATOS_ROOT/tmp"
}

start_jatos() {
    if [ -f "$JATOS_HOME/RUNNING_PID" ] && kill -0 "$(cat "$JATOS_HOME/RUNNING_PID")" 2>/dev/null; then
        fail "JATOS 进程存在但 $BASE_URL/ping 不健康。先执行 (cd $JATOS_HOME && ./loader.sh stop) 再重试。"
    fi
    log "启动 JATOS（端口 ${JATOS_PORT}）"
    (
        cd "$JATOS_HOME"
        nohup ./loader.sh start > "$JATOS_ROOT/jatos-run.log" 2>&1 &
        echo $! > "$JATOS_ROOT/loader.pid"
    )
    local attempt
    for attempt in $(seq 1 90); do
        if jatos_healthy; then
            log "JATOS 已就绪"
            return
        fi
        if [ -f "$JATOS_HOME/RUNNING_PID" ] && ! kill -0 "$(cat "$JATOS_HOME/RUNNING_PID")" 2>/dev/null; then
            break
        fi
        sleep 2
    done
    tail -n 30 "$JATOS_ROOT/jatos-run.log" >&2 || true
    tail -n 30 "$JATOS_HOME/logs/application.log" >&2 || true
    fail "JATOS 未能在 ${BASE_URL} 就绪"
}

ensure_token() {
    local existing code response users admin_id token_response token
    existing=""
    if [ -f "$TOKEN_ENV_FILE" ]; then
        existing="$(sed -n 's/^JATOS_API_TOKEN=//p' "$TOKEN_ENV_FILE" | head -n 1)"
    fi
    if [ -n "$existing" ]; then
        code="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $existing" \
            "$BASE_URL/jatos/api/v1/admin/token" || true)"
        if [ "$code" = "200" ]; then
            export JATOS_API_TOKEN="$existing"
            log "复用 API token：$TOKEN_ENV_FILE"
            return
        fi
    fi

    log "通过 admin 会话创建 API token"
    rm -f "$COOKIE_JAR"
    response="$(curl -s -c "$COOKIE_JAR" -H "Authorization: csrf-bypass" \
        --data-urlencode "username=$JATOS_ADMIN_USER" \
        --data-urlencode "password=$JATOS_ADMIN_PASSWORD" \
        "$BASE_URL/jatos/signin/local" || true)"
    chmod 600 "$COOKIE_JAR" 2>/dev/null || true
    if ! printf '%s' "$response" | grep -q '"redirectUrl"'; then
        rm -f "$COOKIE_JAR"
        log "WARN: admin 登录失败，未自动创建 token。请在 GUI 的 My API tokens 创建，或设置 JATOS_ADMIN_USER/JATOS_ADMIN_PASSWORD。"
        return 0
    fi
    users="$(curl -s -b "$COOKIE_JAR" -H "Authorization: csrf-bypass" \
        "$BASE_URL/jatos/api/v1/users" || true)"
    admin_id="$(printf '%s' "$users" | sed -nE \
        's/.*"username":"'"$JATOS_ADMIN_USER"'","id":([0-9]+).*/\1/p')"
    if [ -z "$admin_id" ]; then
        rm -f "$COOKIE_JAR"
        log "WARN: 未找到 admin 用户 ID，未自动创建 token。"
        return 0
    fi
    token_response="$(curl -s -b "$COOKIE_JAR" -H "Authorization: csrf-bypass" \
        -H "Content-Type: application/json" -d '{"name":"moyo-dev"}' \
        "$BASE_URL/jatos/api/v1/users/$admin_id/tokens" || true)"
    token="$(printf '%s' "$token_response" | sed -nE 's/.*"token":"([^"]+)".*/\1/p')"
    rm -f "$COOKIE_JAR"
    if [ -z "$token" ]; then
        log "WARN: token 生成失败，响应：$token_response"
        return 0
    fi
    (umask 077; printf 'JATOS_API_TOKEN=%s\n' "$token" > "$TOKEN_ENV_FILE")
    chmod 600 "$TOKEN_ENV_FILE"
    export JATOS_API_TOKEN="$token"
    log "API token 已写入 $TOKEN_ENV_FILE"
}

print_summary() {
    local jatos_pid="unknown" listener
    if [ -f "$JATOS_HOME/RUNNING_PID" ]; then
        jatos_pid="$(cat "$JATOS_HOME/RUNNING_PID")"
    fi
    listener="$(lsof -nP -iTCP:"$JATOS_PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}' || true)"
    printf '\n'
    printf 'JATOS_BASE_URL=%s\n' "$BASE_URL"
    printf 'JATOS_APP_DIR=%s\n' "$JATOS_HOME"
    printf 'JATOS_PID=%s\n' "$jatos_pid"
    printf 'JATOS_LOG=%s\n' "$JATOS_HOME/logs/application.log"
    printf 'JATOS_CACHE=%s\n' "$ZIP_PATH"
    if [ -n "$listener" ] && [ "$listener" != "$jatos_pid" ]; then
        printf 'LISTENING_PID=%s (端口 %s 上的进程与 RUNNING_PID 不同)\n' "$listener" "$JATOS_PORT"
    fi
    printf 'MARIADB=127.0.0.1:%s  DB=%s  USER=%s\n' "$JATOS_DB_PORT" "$JATOS_DB_NAME" "$JATOS_DB_USER"
    printf 'ADMIN_USER=%s\n' "$JATOS_ADMIN_USER"
    printf 'ADMIN_PASSWORD：全新数据库的 JATOS 3.11.3 使用默认密码 admin，日志不会输出随机初始密码；如已修改请使用新密码。\n'
    if [ -f "$TOKEN_ENV_FILE" ]; then
        printf 'JATOS_API_TOKEN：在 shell 中执行 source %s，或手动 export；本配置中 token 有效期 1 天，失效后重跑本脚本会生成新 token。\n' "$TOKEN_ENV_FILE"
    else
        printf 'JATOS_API_TOKEN：登录 %s/jatos 后在用户菜单 My API tokens 创建。\n' "$BASE_URL"
    fi
    printf '停止 JATOS：cd %s && ./loader.sh stop\n' "$JATOS_HOME"
    printf '停止 MariaDB：%s --protocol=TCP -h 127.0.0.1 -P %s -u %s shutdown\n' "$MARIADB_ADMIN" "$JATOS_DB_PORT" "$MARIADB_ROOT_USER"
}

main() {
    find_mariadb
    build_root_args
    mkdir -p "$JATOS_ROOT"
    if jatos_healthy; then
        log "JATOS 已在 $BASE_URL 运行，复用现有实例"
    else
        ensure_mariadb
        load_db_password
        ensure_database
        install_jatos
        write_jatos_conf
        export_jatos_env
        start_jatos
    fi
    ensure_token
    print_summary
}

main
