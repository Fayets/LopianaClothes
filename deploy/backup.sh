#!/bin/bash
# Respaldo diario de lo único que no se puede regenerar: la base y las fotos.
# Instalar en cron:  0 4 * * * /srv/lopiana/deploy/backup.sh >> /var/log/lopiana-backup.log 2>&1
set -euo pipefail

APP=${LOPIANA_APP:-/home/deploy/apps/LopianaClothes}
DEST=${LOPIANA_BACKUPS:-/srv/backups/lopiana}
KEEP_DAYS=30
STAMP=$(date +%F_%H%M)

mkdir -p "$DEST"

if [ ! -f "$APP/data/lopiana.db" ]; then
  echo "[$(date +%F\ %T)] ERROR: no encuentro $APP/data/lopiana.db" >&2
  exit 1
fi

# Copia en caliente con la API de backup de SQLite: no corrompe la base ni bloquea la
# tienda mientras alguien esta comprando. Se usa python3 en vez del binario sqlite3
# porque el modulo viene en la biblioteca estandar y no hay que instalar nada de mas.
python3 - "$APP/data/lopiana.db" "$DEST/lopiana_$STAMP.db" <<'SQLPY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
SQLPY

# Un respaldo que no se puede abrir no es un respaldo: se comprueba antes de comprimir.
python3 - "$DEST/lopiana_$STAMP.db" <<'CHECKPY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    sys.exit("La copia no pasa el chequeo de integridad")
n = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
o = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
print(f"  copia verificada: {n} prendas, {o} pedidos")
CHECKPY

gzip -f "$DEST/lopiana_$STAMP.db"

tar -czf "$DEST/media_$STAMP.tar.gz" -C "$APP" media

find "$DEST" -name '*.gz' -mtime +$KEEP_DAYS -delete

echo "[$(date +%F\ %T)] respaldo ok: lopiana_$STAMP.db.gz + media_$STAMP.tar.gz"

# Un respaldo que vive en el mismo disco que el original no es un respaldo. Descomentar
# una vez configurado rclone con el destino remoto (Drive, S3, Backblaze...):
# rclone copy "$DEST" remoto:lopiana-backups --max-age 25h
