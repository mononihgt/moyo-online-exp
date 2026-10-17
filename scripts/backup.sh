#!/usr/bin/env bash
set -euo pipefail
umask 077

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
DAILY_DIR="$BACKUP_ROOT/daily"
WEEKLY_DIR="$BACKUP_ROOT/weekly"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"
DB_ROOT_USER="${DB_ROOT_USER:-root}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:?DB_ROOT_PASSWORD is required}"
DB_NAMES="${DB_NAMES:-moyo jatos}"
MEDIA_DIR="${MEDIA_DIR:-/srv/app_data}"
JATOS_DATA_DIR="${JATOS_DATA_DIR:-/srv/jatos_data}"
DAILY_RETENTION_DAYS="${DAILY_RETENTION_DAYS:-7}"
WEEKLY_RETENTION_DAYS="${WEEKLY_RETENTION_DAYS:-28}"
BACKUP_HOUR="${BACKUP_HOUR:-02}"

WORK_DIR=""

log() {
  printf '%s %s\n' "$(date '+%F %T %Z')" "$*"
}

cleanup() {
  if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT
trap 'exit 0' TERM INT

require_dir() {
  if [ ! -d "$1" ]; then
    printf 'error: directory not found: %s\n' "$1" >&2
    exit 1
  fi
}

run_backup() {
  require_dir "$MEDIA_DIR"
  require_dir "$JATOS_DATA_DIR"
  mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

  exec 9>"$BACKUP_ROOT/.backup.lock"
  if ! flock -n 9; then
    printf 'error: another backup is already running\n' >&2
    exit 1
  fi

  local timestamp target_dir week_key db
  local -a databases
  timestamp="$(date '+%Y%m%dT%H%M%S')"
  week_key="$(date '+%G-W%V')"
  target_dir="$DAILY_DIR/$timestamp"
  WORK_DIR="$BACKUP_ROOT/.incomplete-$timestamp-$$"
  mkdir -p "$WORK_DIR"

  log "backup started: $timestamp"
  export MYSQL_PWD="$DB_ROOT_PASSWORD"
  read -r -a databases <<< "$DB_NAMES"
  if [ "${#databases[@]}" -eq 0 ]; then
    printf 'error: DB_NAMES must contain at least one database\n' >&2
    exit 1
  fi
  for db in "${databases[@]}"; do
    log "dumping database $db"
    mariadb-dump \
      --host="$DB_HOST" \
      --port="$DB_PORT" \
      --user="$DB_ROOT_USER" \
      --single-transaction \
      --quick \
      --routines \
      --triggers \
      --events \
      --hex-blob \
      --default-character-set=utf8mb4 \
      "$db" | gzip -c > "$WORK_DIR/$db.sql.gz"
    test -s "$WORK_DIR/$db.sql.gz"
  done
  unset MYSQL_PWD

  log "archiving platform data"
  tar -czf "$WORK_DIR/app_data.tar.gz" -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")"

  log "archiving JATOS data"
  # JATOS 临时目录在运行期间持续变化，恢复时不需要。
  tar -czf "$WORK_DIR/jatos_data.tar.gz" \
    --exclude="$(basename "$JATOS_DATA_DIR")/tmp" \
    -C "$(dirname "$JATOS_DATA_DIR")" \
    "$(basename "$JATOS_DATA_DIR")"

  (
    cd "$WORK_DIR"
    sha256sum ./*.sql.gz ./*.tar.gz > SHA256SUMS
  )
  {
    printf 'created_at=%s\n' "$(date '+%FT%T%z')"
    printf 'host=%s\n' "$(hostname)"
    printf 'databases=%s\n' "$DB_NAMES"
    printf 'daily=%s\n' "$target_dir"
    printf 'weekly=%s\n' "$WEEKLY_DIR/$week_key"
  } > "$WORK_DIR/manifest.txt"

  mv "$WORK_DIR" "$target_dir"
  WORK_DIR=""
  log "backup written: $target_dir"

  if [ ! -e "$WEEKLY_DIR/$week_key" ]; then
    cp -al "$target_dir" "$WEEKLY_DIR/$week_key"
    log "weekly backup written: $WEEKLY_DIR/$week_key"
  fi

  find "$DAILY_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +$((DAILY_RETENTION_DAYS - 1)) -exec rm -rf {} +
  find "$WEEKLY_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +$((WEEKLY_RETENTION_DAYS - 1)) -exec rm -rf {} +

  flock -u 9
  exec 9>&-
  log "backup finished"
}

next_backup_epoch() {
  local now target
  now="$(date '+%s')"
  target="$(date -d "today ${BACKUP_HOUR}:00:00" '+%s')"
  if [ "$target" -le "$now" ]; then
    target="$(date -d "tomorrow ${BACKUP_HOUR}:00:00" '+%s')"
  fi
  printf '%s\n' "$target"
}

daemon_loop() {
  mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"
  local today target
  today="$(date '+%F')"
  if [ -z "$(find "$DAILY_DIR" -mindepth 1 -maxdepth 1 -type d -newermt "$today 00:00:00" -print -quit)" ]; then
    run_backup
  fi
  while true; do
    target="$(next_backup_epoch)"
    log "next backup scheduled: $(date -d "@$target" '+%F %T %Z')"
    sleep $((target - $(date '+%s')))
    run_backup
  done
}

case "${1:-once}" in
  once)
    run_backup
    ;;
  daemon)
    daemon_loop
    ;;
  *)
    printf 'usage: %s [once|daemon]\n' "$0" >&2
    exit 2
    ;;
esac
