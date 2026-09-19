# Prompts para deployar Lopiana en un VPS que ya tiene otros sistemas

Para pegar de a uno en una sesión de agente **dentro del VPS**. Van en orden y cada uno
es autosuficiente: no asumen que el agente vio los anteriores ni esta conversación.

La regla que atraviesa todos: **el VPS ya tiene otros sistemas corriendo y no se toca
ninguno.** Nada de puertos asumidos, nada de reinstalar el proxy, nada de reescribir
configuración ajena.

---

## Prompt 1 — Auditoría (no cambia nada)

```
Vas a preparar el deploy de una app nueva en este VPS, pero ANTES no cambies
absolutamente nada: este servidor ya tiene otros sistemas en producción y no se pueden
tocar ni interrumpir.

Hacé un relevamiento de solo lectura y devolveme un informe:

1. Qué hay corriendo: `systemctl list-units --type=service --state=running`
2. Qué puertos están ocupados: `ss -tlnp`
3. Qué proxy inverso hay instalado y activo: nginx, Caddy, Apache, Traefik o ninguno.
   Mostrame cuál corre, su versión, y el contenido del directorio de sitios
   (/etc/nginx/sites-enabled, /etc/caddy/Caddyfile, etc.)
4. Qué dominios/subdominios sirve hoy ese proxy
5. Cómo se resuelven los certificados TLS hoy (certbot, Caddy automático, Cloudflare)
6. Qué versión de Python hay: `python3 --version`
7. Qué hay en /srv, /opt y /var/www
8. Si hay cron jobs o timers de systemd ya configurados: `crontab -l`,
   `systemctl list-timers`
9. Espacio en disco: `df -h`

No instales nada, no edites archivos, no reinicies servicios. Solo informá.

Al final decime, concretamente:
- Qué puerto local está libre para una app nueva (proponeme uno entre 8020 y 8099 que
  NO esté en uso)
- Si el proxy que ya está puede sumar un sitio más sin tocar los existentes
```

---

## Prompt 2 — Subir el código (se corre en la Mac, no en el VPS)

Reemplazá `USUARIO@IP` por lo tuyo. Esto lo corrés vos desde la terminal de tu Mac:

```bash
rsync -avz --delete \
  --exclude 'data/' --exclude 'media/' --exclude '__pycache__/' --exclude '.DS_Store' \
  ~/Desktop/LopianaClothes/ USUARIO@IP:/srv/lopiana/
```

`data/` y `media/` quedan excluidos a propósito: son la base y las fotos del servidor.
Si los mandaras, pisarías los pedidos y el stock reales con los de tu máquina.

---

## Prompt 3 — Instalar la app aislada

```
En /srv/lopiana está el código de una tienda: FastAPI + SQLite + Pillow, entrypoint
`app.main:app`. Necesita Python 3.11 o superior.

Este VPS tiene otros sistemas en producción. Instalá esta app SIN tocar nada de lo
existente: no toques los venv de otras apps, no instales paquetes de Python a nivel
sistema, no modifiques servicios ajenos.

Hacé esto:

1. Creá un usuario de sistema propio para la app:
   `adduser --system --group --home /srv/lopiana lopiana`
   (si /srv/lopiana ya existe con el código, no lo borres, solo ajustá el dueño después)

2. Creá un virtualenv PROPIO en /srv/lopiana/.venv e instalá ahí
   /srv/lopiana/requirements.txt. Nada fuera de ese venv.

3. Copiá /srv/lopiana/.env.example a /srv/lopiana/.env y completalo:
   - LOPIANA_HOSTS = el dominio que voy a usar (preguntámelo si no te lo dije)
   - LOPIANA_HTTPS=1
   - LOPIANA_TRUST_PROXY=1
   - LOPIANA_ADMIN_PIN = generá uno aleatorio de 12 caracteres y MOSTRÁMELO al final,
     no lo inventes silenciosamente

4. Inicializá la base: `sudo -u lopiana /srv/lopiana/.venv/bin/python -m app.seed`
   Esto crea data/lopiana.db con el catálogo inicial. Si data/lopiana.db ya existe,
   NO la toques: el esquema se migra solo al arrancar.

5. Permisos:
   `chown -R lopiana:lopiana /srv/lopiana`
   `chmod 600 /srv/lopiana/.env`

6. Instalá el servicio desde /srv/lopiana/deploy/lopiana.service en
   /etc/systemd/system/. IMPORTANTE: antes de habilitarlo, editá el ExecStart para que
   use el puerto libre que corresponda (el archivo viene con 8020; si ese puerto está
   ocupado por otro sistema, cambialo). Confirmá con `ss -tlnp` que está libre.
   La app DEBE escuchar en 127.0.0.1, nunca en 0.0.0.0.

7. `systemctl daemon-reload && systemctl enable --now lopiana`

8. Verificá que responde localmente:
   `curl -s -o /dev/null -w "%{http_code}" -H "Host: EL_DOMINIO" http://127.0.0.1:PUERTO/`
   Tiene que dar 200. Si da 400, el Host no coincide con LOPIANA_HOSTS.

9. Confirmá que NO rompiste nada: `systemctl list-units --type=service --state=failed`
   y que los otros servicios que estaban corriendo siguen corriendo.

Decime al final: el puerto que usaste, el PIN generado, y el estado del servicio.
```

---

## Prompt 4A — Proxy, si ya hay **nginx**

```
Este VPS ya sirve otros sitios con nginx. Quiero sumar uno más SIN tocar los que ya
están: no edites nginx.conf ni los vhosts existentes, no reinicies nginx sin antes
validar la configuración.

La app nueva corre en 127.0.0.1:PUERTO (decime si no sabés cuál) y el dominio es DOMINIO.

1. Creá un vhost NUEVO en /etc/nginx/sites-available/lopiana con:
   - server_name para el dominio y su www
   - proxy_pass a http://127.0.0.1:PUERTO
   - proxy_set_header Host $host
   - proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for
   - proxy_set_header X-Forwarded-Proto $scheme
   - client_max_body_size 30M  (las fotos de celular pasan los 10M por defecto)
   - location /media/ { proxy_pass ...; expires 30d; }  las fotos tienen nombre único
   - location ~ ^/(admin|api/admin) { proxy_pass ...; add_header Cache-Control "no-store"; }

2. Enlazalo en sites-enabled y validá ANTES de recargar: `nginx -t`.
   Si `nginx -t` falla, arreglá el archivo nuevo. Nunca recargues con la config rota:
   te llevás puestos los otros sitios.

3. `systemctl reload nginx` (reload, no restart)

4. TLS: mirá cómo se emiten los certificados de los otros sitios y usá el MISMO método.
   Si es certbot: `certbot --nginx -d DOMINIO -d www.DOMINIO`. Si los otros sitios están
   detrás de Cloudflare, decímelo antes de emitir nada.

5. Verificá que los sitios que ya estaban siguen respondiendo (probá cada dominio que
   viste en el relevamiento) y que el nuevo también.

Ignorá /srv/lopiana/deploy/Caddyfile: ese archivo es para el caso de que no hubiera
proxy. Acá manda nginx.
```

---

## Prompt 4B — Proxy, si ya hay **Caddy**

```
Este VPS ya sirve otros sitios con Caddy. Quiero sumar uno más sin tocar los existentes.

La app nueva corre en 127.0.0.1:PUERTO y el dominio es DOMINIO.

1. Mirá /etc/caddy/Caddyfile y decime si usa bloques por sitio en el mismo archivo o
   `import` de un directorio (por ejemplo /etc/caddy/sites/*).

2. Agregá SOLO un bloque nuevo, tomando como base
   /srv/lopiana/deploy/Caddyfile (cambiá el dominio y el puerto del reverse_proxy).
   Si el Caddyfile usa `import`, poné el bloque en un archivo aparte en ese directorio
   en vez de mezclarlo en el principal.

3. Validá antes de aplicar: `caddy validate --config /etc/caddy/Caddyfile`

4. `systemctl reload caddy`

5. Caddy pide el certificado solo la primera vez que alguien entra al dominio nuevo.
   Confirmá que el DNS del dominio ya apunta a este servidor ANTES de recargar, o el
   pedido va a fallar y va a quedar en reintentos.

6. Verificá que los otros sitios siguen respondiendo.
```

---

## Prompt 4C — Proxy, si **no hay ninguno**

```
Este VPS tiene otros sistemas corriendo pero ninguno usa un proxy inverso (los puertos
80 y 443 están libres). Confirmalo con `ss -tlnp` antes de seguir.

Instalá Caddy y configuralo desde /srv/lopiana/deploy/Caddyfile, cambiando el dominio y
el puerto del reverse_proxy por los que correspondan. Caddy resuelve HTTPS solo.

Si al verificar encontrás que algo YA está escuchando en 80 o 443, frená y avisame:
instalar Caddy ahí tiraría abajo lo que esté sirviendo esos puertos.
```

---

## Prompt 5 — Respaldos, sin pisar los que ya existan

```
Quiero respaldo diario de una app en /srv/lopiana. Lo único irrecuperable es
/srv/lopiana/data/lopiana.db (pedidos y stock) y /srv/lopiana/media/ (las fotos).

Este VPS ya tiene otros sistemas y puede tener respaldos configurados. Antes de agregar
nada, mostrame `crontab -l`, `ls /etc/cron.d/` y `systemctl list-timers`, y decime si ya
hay un esquema de respaldo andando.

- Si YA hay uno: sumate a ese esquema en vez de crear uno paralelo. Mostrame cómo
  quedaría integrado antes de tocar nada.
- Si NO hay: instalá /srv/lopiana/deploy/backup.sh en cron a las 4 AM, agregando una
  línea nueva sin borrar las que ya estén:
  `0 4 * * * /srv/lopiana/deploy/backup.sh >> /var/log/lopiana-backup.log 2>&1`

En los dos casos:
1. Creá /srv/backups/lopiana
2. Corré el script UNA VEZ a mano y mostrame la salida y los archivos que generó
3. Probá que el respaldo sirve: descomprimí la copia de la base en /tmp y corré
   `sqlite3 /tmp/prueba.db "select count(*) from products;"`. Un respaldo que no se
   probó no es un respaldo.
4. Al final del script hay un `rclone copy` comentado. Decime si este VPS ya tiene
   rclone configurado con algún remoto y cuál, para mandar la copia fuera del servidor.
   Mientras el respaldo viva en el mismo disco que el original, no protege de nada.
```

---

## Prompt 6 — Verificación final

```
Verificá que la tienda en DOMINIO quedó bien y que no rompí nada de lo que ya había.
Mostrame el resultado de cada punto:

De la app nueva:
1. `curl -sI https://DOMINIO/` da 200 y viaja por HTTPS
2. Las cabeceras traen Content-Security-Policy, Strict-Transport-Security,
   X-Frame-Options y X-Content-Type-Options
3. `curl -s https://DOMINIO/api/admin/products` da 401 (el panel no se abre sin sesión)
4. `curl -sI https://DOMINIO/docs` da 404 (la documentación de la API no está expuesta)
5. Un Host que no sea el mío da 400:
   `curl -sI -H "Host: evil.com" https://DOMINIO/`
6. La app NO escucha en 0.0.0.0: `ss -tlnp | grep PUERTO` tiene que mostrar 127.0.0.1
7. `systemctl status lopiana` activo, y probá `systemctl restart lopiana` para
   confirmar que vuelve sola
8. Entrá a https://DOMINIO/admin: tiene que pedir el PIN, y al entrar con el PIN
   provisorio tiene que obligar a cambiarlo

De lo que ya estaba:
9. Cada dominio que viste en el relevamiento inicial sigue respondiendo
10. `systemctl list-units --type=service --state=failed` sin novedades
11. Los puertos que estaban ocupados antes siguen ocupados por los mismos procesos

Si algo de lo de arriba falla, decímelo sin arreglarlo por tu cuenta.
```

---

## Si algo sale mal

```
La tienda en DOMINIO no responde / da error. Diagnosticá sin tocar los otros sistemas:

- `journalctl -u lopiana -n 100 --no-pager`   (errores de la app)
- `systemctl status lopiana`
- `curl -v -H "Host: DOMINIO" http://127.0.0.1:PUERTO/`   (¿responde la app sin el proxy?)
- logs del proxy (nginx: /var/log/nginx/error.log; caddy: `journalctl -u caddy`)

Errores frecuentes:
- 400 "Invalid host header" → el dominio no está en LOPIANA_HOSTS del .env
- 502 → la app no está corriendo, o el proxy apunta al puerto equivocado
- 413 al subir una foto → falta `client_max_body_size 30M` en nginx
- El panel deja entrar pero se desloguea solo → la cookie es Secure y estás entrando
  por http; tiene que ser https
- Se perdió el PIN → borrar la fila `admin_pin_hash` de la tabla settings
  (`sqlite3 /srv/lopiana/data/lopiana.db "delete from settings where key='admin_pin_hash';"`)
  y reiniciar el servicio: vuelve al PIN provisorio y te obliga a elegir uno nuevo
```

---

## Actualizar la tienda más adelante

Desde la Mac:

```bash
rsync -avz --delete \
  --exclude 'data/' --exclude 'media/' --exclude '__pycache__/' --exclude '.DS_Store' \
  ~/Desktop/LopianaClothes/ USUARIO@IP:/srv/lopiana/
ssh USUARIO@IP 'chown -R lopiana:lopiana /srv/lopiana && systemctl restart lopiana'
```

El esquema de la base se migra solo al arrancar. `data/` y `media/` nunca se tocan.
