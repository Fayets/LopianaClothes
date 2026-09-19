#!/bin/bash
# Inserta un bloque server en el nginx.conf que comparten Coquetines, Aire de los Cerros
# y sops, SIN dejarlos caídos si algo sale mal:
#
#   1. copia de seguridad con fecha
#   2. inserta el bloque antes del } que cierra http { }
#   3. valida con nginx -t DENTRO del contenedor
#   4. si la validación falla, restaura la copia y sale sin recargar
#   5. si pasa, recarga en caliente (sin cortar las conexiones abiertas)
#
# Uso:  ./add-to-nginx.sh archivo-con-el-bloque.conf
set -euo pipefail

CONF=${NGINX_CONF:-/home/deploy/apps/Coquetines/nginx.conf}
CONTAINER=${NGINX_CONTAINER:-coquetines_nginx}
BLOCK=${1:?Falta el archivo con el bloque server a insertar}

[ -f "$CONF" ]  || { echo "No existe $CONF"; exit 1; }
[ -f "$BLOCK" ] || { echo "No existe $BLOCK"; exit 1; }

BACKUP="$CONF.bak.$(date +%Y%m%d_%H%M%S)"
cp "$CONF" "$BACKUP"
echo "Copia de seguridad: $BACKUP"

python3 - "$CONF" "$BLOCK" <<'PY'
import sys
conf_path, block_path = sys.argv[1], sys.argv[2]
lines = open(conf_path).read().rstrip("\n").split("\n")
# El último } del archivo cierra el bloque http { }: el nuestro va justo antes.
last = max(i for i, l in enumerate(lines) if l.strip() == "}")
block = [l for l in open(block_path).read().split("\n") if not l.lstrip().startswith("#")]
while block and not block[0].strip():
    block.pop(0)
while block and not block[-1].strip():
    block.pop()
lines[last:last] = ["", "    # ---- Lopiana Clothes ----"] + ["    " + l if l.strip() else l for l in block] + [""]
open(conf_path, "w").write("\n".join(lines) + "\n")
PY

echo "Bloque insertado. Validando dentro de $CONTAINER..."
if docker exec "$CONTAINER" nginx -t; then
    docker exec "$CONTAINER" nginx -s reload
    echo "OK: configuración válida y nginx recargado."
else
    cp "$BACKUP" "$CONF"
    echo "FALLÓ la validación. Se restauró $BACKUP y NO se recargó nginx."
    echo "Los sitios que ya andaban siguen intactos."
    exit 1
fi
