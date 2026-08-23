#!/bin/sh
# Суточный бэкап базы аналитики: снимок → gzip на хост → Google Диск.
#
# Зачем отдельный скрипт, а не «cat файла»: приложение пишет в базу постоянно
# (планировщик синкает каждые 3 минуты), и обычная копия файла на живой базе
# получается рваной — страницы из разных моментов. sqlite3.Connection.backup()
# делает согласованный снимок под блокировкой самой SQLite, не останавливая
# приложение. python3 и gzip есть внутри контейнера, ставить ничего не нужно.
#
# В базе лежит то, чего нет в iiko: поставщики, цены, ТТК, себестоимость —
# всё вбито руками и из внешнего API не восстанавливается. Плюс миграций в
# проекте нет, и смена схемы делается через `down -v`, то есть с удалением
# тома. Одна такая операция без копии — и данные исчезают навсегда.
#
# `copy`, а не `sync`: локально держим 30 последних копий, sync удалял бы на
# Диске всё, что старше, — ровно тот архив, ради которого всё затевалось.
#
# На сервере лежит как /root/dashboards-backup.sh — НЕ внутри /root/dashboards,
# чтобы не мешать `git pull` при деплое. Здесь хранится эталон; после правки
# скопировать на сервер:
#   scp ops/backup.sh root@<host>:/root/dashboards-backup.sh
set -eu

# Ничего не берём из окружения: крон запускает скрипт почти с пустым env.
# Без явного PATH нет docker и rclone, без --config rclone ищет конфиг по
# $HOME, которого в кроне тоже нет, — проверено на бэкапе сайта.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

CONT=dashboards-backend-1
DB=/data/iskendi.db
SNAP=/tmp/iskendi-backup.db          # временный снимок внутри контейнера
DIR=/root/backups/analytics
DEST="gdrive:Искенди — бэкапы аналитики"
CONF=/root/.config/rclone/rclone.conf
KEEP=30
LOG=/var/log/iskendy-analytics-backup.log
GUARD=/root/iskendy/guard.sh

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$DIR/iskendi-$STAMP.db.gz"
mkdir -p "$DIR"

log() { echo "$(date -Is) $*" >> "$LOG"; }

# Тревога и её развязка — через сторож сайта: он уже умеет разбирать .env,
# ходить через прокси и не спамить повторами. Своей отправки не заводим.
raise()   { [ -x "$GUARD" ] && "$GUARD" --raise   "$1" "$2" 2>/dev/null || true; }
resolve() { [ -x "$GUARD" ] && "$GUARD" --resolve "$1" "$2" 2>/dev/null || true; }

log "=== бэкап начался ==="

# ------------------------------------------------------------ снимок базы
# integrity_check прямо на снимке: битую копию лучше не отправлять и не
# засчитывать — иначе тревога не сработает, а бэкапа фактически не будет.
if ! CHECK=$(docker exec -i "$CONT" python3 - "$DB" "$SNAP" <<'PY' 2>&1
import sqlite3, sys, os
db, snap = sys.argv[1], sys.argv[2]
if os.path.exists(snap):
    os.remove(snap)
src = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
dst = sqlite3.connect(snap)
src.backup(dst)          # согласованный снимок на живой базе
src.close()
dst.close()
con = sqlite3.connect("file:%s?mode=ro" % snap, uri=True)
ok = con.execute("PRAGMA integrity_check").fetchone()[0]
tables = con.execute(
    "SELECT count(*) FROM sqlite_master WHERE type='table'"
).fetchone()[0]
con.close()
if ok != "ok":
    sys.exit("integrity_check: %s" % ok)
print("%s таблиц, integrity_check=ok, %d байт" % (tables, os.path.getsize(snap)))
PY
); then
  log "ОШИБКА снимка: $CHECK"
  raise analytics_backup_snapshot "🔴 <b>Бэкап аналитики не снялся</b>
Копия базы за сегодня не сделана. В базе поставщики, цены и ТТК — из iiko они не восстанавливаются.
Смотреть: $LOG"
  exit 1
fi
log "снимок: $CHECK"

docker exec "$CONT" gzip -c "$SNAP" > "$OUT"
docker exec "$CONT" rm -f "$SNAP"

# Пустой или обрезанный архив считаем провалом: файл на диске есть, а бэкапа нет.
if [ ! -s "$OUT" ] || ! gzip -t "$OUT" 2>/dev/null; then
  log "ОШИБКА: архив $OUT битый или пуст"
  rm -f "$OUT"
  raise analytics_backup_snapshot "🔴 <b>Бэкап аналитики не снялся</b>
Архив получился битым. Смотреть: $LOG"
  exit 1
fi
log "архив: $OUT ($(du -h "$OUT" | cut -f1))"
resolve analytics_backup_snapshot "✅ Бэкап аналитики снова снимается"

# ------------------------------------------------------------- ротация 30
# Удаляем только по своему шаблону имени, чтобы случайные файлы в каталоге
# не попали под раздачу.
ls -1t "$DIR"/iskendi-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old" && log "удалена старая копия: $old"
done

# --------------------------------------------------------- выгрузка наружу
# rclone ходит в Google под общим client_id и упирается в поминутную квоту:
# 403 rateLimitExceeded ловится и на одном файле в сутки — отсюда --retries и
# вторая попытка через пять минут, прежде чем звать людей.
upload() {
  rclone --config "$CONF" copy "$DIR" "$DEST" \
    --include "iskendi-*.db.gz" \
    --retries 5 --retries-sleep 30s --low-level-retries 10 \
    --stats-one-line >> "$LOG" 2>&1
}

if upload; then
  log "выгружено на Диск"
  resolve analytics_backup_drive "✅ Бэкап аналитики снова уезжает на Google Диск"
else
  log "первая попытка выгрузки не удалась, повтор через 5 минут"
  sleep 300
  if upload; then
    log "выгружено со второй попытки"
    resolve analytics_backup_drive "✅ Бэкап аналитики снова уезжает на Google Диск"
  else
    log "ОШИБКА выгрузки, обе попытки"
    raise analytics_backup_drive "🔴 <b>Бэкап аналитики не уехал на Google Диск</b>
Две попытки подряд не удались. Копия за сегодня осталась только на сервере — если он умрёт, она умрёт вместе с ним.
Смотреть: $LOG"
    exit 1
  fi
fi

log "=== бэкап завершён ==="
