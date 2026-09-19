#!/bin/bash
# Respaldo diario de lo único que no se puede regenerar: la base y las fotos.
# Instalar en cron:  0 4 * * * /srv/lopiana/deploy/backup.sh >> /var/log/lopiana-backup.log 2>&1
set -euo pipefail

APP=/srv/lopiana
DEST=/srv/backups/lopiana
KEEP_DAYS=30
STAMP=$(date +%F_%H%M)

mkdir -p "$DEST"

# sqlite3 .backup copia en caliente sin corromper la base ni bloquear la tienda.
sqlite3 "$APP/data/lopiana.db" ".backup '$DEST/lopiana_$STAMP.db'"
gzip -f "$DEST/lopiana_$STAMP.db"

tar -czf "$DEST/media_$STAMP.tar.gz" -C "$APP" media

find "$DEST" -name '*.gz' -mtime +$KEEP_DAYS -delete

echo "[$(date +%F\ %T)] respaldo ok: lopiana_$STAMP.db.gz + media_$STAMP.tar.gz"

# Un respaldo que vive en el mismo disco que el original no es un respaldo. Descomentar
# una vez configurado rclone con el destino remoto (Drive, S3, Backblaze...):
# rclone copy "$DEST" remoto:lopiana-backups --max-age 25h
