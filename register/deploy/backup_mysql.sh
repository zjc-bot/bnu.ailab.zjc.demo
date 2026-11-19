#!/usr/bin/env bash
# 在本地 Git Bash 或服务器 Bash 中备份 MySQL 8.0；需要 mysqldump 与 gzip。
# 默认写入仓库的 backup/mysql/（已被 .gitignore 排除），也可用 BACKUP_DIR 指定。
#
# 用法（密码只注入当前进程环境，不作为命令行参数，也不写入脚本或配置）：
#   export DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=studentapp DB_NAME=school
#   read -rsp "MySQL password: " DB_PASSWORD; export DB_PASSWORD; printf '\n'
#   bash register/deploy/backup_mysql.sh
#   unset DB_PASSWORD
# 可选：BACKUP_DIR=/受保护/备份目录。文件权限为 0600，请勿用 bash -x 运行。
#
# 恢复（会替换同名表，先确认目标实例，并优先在隔离环境演练）：
#   export DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=恢复账号 DB_NAME=school
#   read -rsp "MySQL password: " DB_PASSWORD; export DB_PASSWORD; printf '\n'
#   gzip -dc backup/mysql/school-时间戳-进程号.sql.gz | \
#     MYSQL_PWD="$DB_PASSWORD" mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER"
#   unset DB_PASSWORD
# 备份含 CREATE DATABASE 与 USE，无需在 mysql 命令后追加库名；恢复前应先备份当前库。

set -euo pipefail
set +x
umask 077

DB_HOST=${DB_HOST:-127.0.0.1}
DB_PORT=${DB_PORT:-3306}
DB_NAME=${DB_NAME:-school}
: "${DB_USER:?请设置 DB_USER}"
: "${DB_PASSWORD:?请通过环境变量设置 DB_PASSWORD}"

case "$DB_NAME" in
    ""|*[!A-Za-z0-9_]*)
        printf 'DB_NAME 只能包含字母、数字和下划线。\n' >&2
        exit 1
        ;;
esac

for cmd in mysqldump gzip mktemp mv; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf '缺少命令：%s\n' "$cmd" >&2
        exit 1
    }
done

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
BACKUP_DIR=${BACKUP_DIR:-"$REPO_ROOT/backup/mysql"}
mkdir -p -- "$BACKUP_DIR"

# 时间戳加进程号降低重名概率；mv -n 和临时文件检查确保绝不覆盖旧备份。
output="${BACKUP_DIR%/}/${DB_NAME}-$(date -u +%Y%m%dT%H%M%SZ)-$$.sql.gz"
tmp=$(mktemp "${BACKUP_DIR%/}/.mysql-backup.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
trap 'exit 1' HUP INT TERM

if ! MYSQL_PWD="$DB_PASSWORD" mysqldump \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --single-transaction \
    --quick \
    --routines \
    --events \
    --triggers \
    --hex-blob \
    --default-character-set=utf8mb4 \
    --set-gtid-purged=OFF \
    --no-tablespaces \
    --databases "$DB_NAME" | gzip >"$tmp"; then
    printf '备份失败，临时文件已清理；旧备份未改动。\n' >&2
    exit 1
fi

if [[ ! -s "$tmp" ]]; then
    printf '备份结果为空，未生成正式备份文件。\n' >&2
    exit 1
fi

mv -n -- "$tmp" "$output"
if [[ -e "$tmp" ]]; then
    printf '目标文件已存在，未覆盖：%s\n' "$output" >&2
    exit 1
fi

trap - EXIT
printf '备份完成：%s\n' "$output"
