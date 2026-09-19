# Poner Lopiana en un VPS

Ubuntu 22.04+ con un dominio apuntando al servidor. Todo como root salvo donde se indica.

## 1. Sistema y usuario

```bash
apt update && apt install -y python3-venv python3-pip sqlite3 caddy
adduser --system --group --home /srv/lopiana lopiana
```

## 2. Código

Subir el proyecto a `/srv/lopiana` (rsync, git clone, lo que sea) y:

```bash
cd /srv/lopiana
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Editar `.env`: poner el dominio real en `LOPIANA_HOSTS` y elegir `LOPIANA_ADMIN_PIN`.
Si se deja vacío, el PIN arranca en `1234` y el panel obliga a cambiarlo al primer ingreso.

```bash
.venv/bin/python -m app.seed      # solo si la base todavía no existe
chown -R lopiana:lopiana /srv/lopiana
chmod 600 /srv/lopiana/.env
```

## 3. Servicio

```bash
cp deploy/lopiana.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now lopiana
systemctl status lopiana
```

## 4. HTTPS

```bash
cp deploy/Caddyfile /etc/caddy/Caddyfile   # cambiar el dominio adentro
systemctl reload caddy
```

Caddy pide el certificado solo la primera vez que alguien entra y lo renueva sin intervención.

## 5. Respaldos

```bash
mkdir -p /srv/backups/lopiana
crontab -e
# agregar:
0 4 * * * /srv/lopiana/deploy/backup.sh >> /var/log/lopiana-backup.log 2>&1
```

Correrlo una vez a mano para confirmar que funciona, y configurar el `rclone copy` del final
del script: un respaldo en el mismo disco que el original no sirve si se pierde el disco.

## 6. Firewall

```bash
ufw allow 22,80,443/tcp && ufw enable
```

La app escucha en `127.0.0.1:8020`, así que no se llega a ella salvo a través de Caddy.

## Actualizar

```bash
cd /srv/lopiana && git pull        # o rsync
.venv/bin/pip install -r requirements.txt
systemctl restart lopiana
```

El esquema se migra solo al arrancar. `data/` y `media/` nunca se tocan.

## Qué mira cuando algo falla

```bash
journalctl -u lopiana -f          # errores de la app
tail -f /var/log/caddy/lopiana.log
```

## Lo que quedó cubierto

- El PIN se guarda hasheado (scrypt), nunca en claro.
- La sesión es un token aleatorio con vencimiento a 14 días, revocable. Cambiar el PIN cierra
  todas las sesiones abiertas.
- El login se bloquea 15 minutos tras 6 intentos fallidos desde la misma IP.
- Cuota por IP en los endpoints públicos: 6 pedidos/hora, 5 suscripciones/10 min, 120 eventos/min.
- Cabeceras: CSP, HSTS, nosniff, X-Frame-Options, Referrer-Policy.
- Solo se aceptan los dominios de `LOPIANA_HOSTS`.
- Las subidas se validan como imágenes reales y se cortan en 25 MB y 60 megapíxeles.

## Lo que no

- Un solo proceso uvicorn. Las cuotas viven en memoria, así que si algún día se agregan
  workers hay que moverlas a la base. Para el volumen de una tienda de autor, sobra.
- No hay recuperación de PIN por mail: si se pierde, se resetea desde el servidor borrando
  la fila `admin_pin_hash` de la tabla `settings` y reiniciando el servicio.
