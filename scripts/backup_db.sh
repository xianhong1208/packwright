#!/bin/bash
# Back up Packwright's database (SQLite or PostgreSQL) to a gzip file.
#
# The database holds what cannot be rebuilt from code: build history (with the
# exact config of every build), users and roles, audit logs, login records.
# Workspaces and artifacts have a TTL and come back by rerunning a build.
#
# The database is found exactly as the service finds it (DATABASE_URL, then
# DB_*, then the default SQLite file); the work is in app/services/db_backup.py.
#
# Usage:
#   bash scripts/backup_db.sh                    # into ./data/backups, keep 30 days
#   BACKUP_DIR=/mnt/nas/packwright RETENTION_DAYS=60 bash scripts/backup_db.sh
#
# Recommended cron (daily at 03:30):
#   30 3 * * * cd /opt/packwright && bash scripts/backup_db.sh >> /var/log/packwright_backup.log 2>&1
#
# Restore (stop the service first):
#   SQLite:      gunzip -c <file>.sqlite.gz > data/build_center.db
#   PostgreSQL:  gunzip -c <file>.sql.gz | psql -h HOST -U USER -d DBNAME

set -euo pipefail

cd "$(dirname "$0")/.."
exec uv run python -m app.services.db_backup
