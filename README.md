# Lopiana Clothes · landing + pedidos por WhatsApp

Tienda sin pasarela de pago: la clienta elige la prenda, arma el carrito y el pedido se envía por WhatsApp. Todo lo demás (stock, pedidos, fotos, métricas) se gestiona desde un panel local.

## Correr

```bash
./run.sh
```

- Tienda: http://localhost:8020
- Panel de gestión: http://localhost:8020/admin

Requiere Python 3.11+. `run.sh` instala dependencias, carga el producto inicial si no existe y levanta el servidor.

El PIN inicial sale de `LOPIANA_ADMIN_PIN`. Sin esa variable arranca en `1234` y el panel
**obliga a cambiarlo** antes de dejar entrar. Mínimo 6 caracteres. Se cambia después en Ajustes.

Para publicarlo en un servidor: [`deploy/README.md`](deploy/README.md).

## Qué hay

| Carpeta | Qué es |
|---|---|
| `app/main.py` | API (FastAPI): productos, eventos, pedidos, panel |
| `app/db.py` | Esquema SQLite (`data/lopiana.db`) y migraciones |
| `app/security.py` | PIN hasheado, sesiones, límite de intentos y cuotas por IP |
| `app/images.py` | Normalización de fotos: todas salen en 1200×1600 (3:4) |
| `app/seed.py` | Carga inicial desde `seed_img/catalog.json` (8 prendas, 3 categorías); no duplica lo que ya existe |
| `static/index.html` | Tienda: hero, categorías, grilla, ficha (modal) y carrito |
| `static/admin.html` | Panel de gestión |
| `media/products/` | Fotos normalizadas por producto |
| `media/originals/` | Fotos tal cual se subieron (para reprocesar) |
| `deploy/` | Caddyfile, unit de systemd, respaldo y guía de puesta en el VPS |

## Qué carga la clienta en cada prenda

Todo desde el panel, y desde el celular tanto como desde la compu:

| Campo | Dónde se ve en la tienda |
|---|---|
| Nombre, categoría, precios | Grilla y ficha |
| Descripción | Ficha, debajo del acordeón |
| **Foto principal** | La primera de la galería: es la de la grilla y la que abre la ficha. Cualquier foto se asciende con **Hacer principal** |
| **Galería** | Miniaturas de la ficha, reordenables |
| **Tabla de talles** | Botón *Ver tabla de talles* en la ficha, abre en una ventana propia |
| **Talles y stock** | Botones de talle; el stock se descuenta con cada pedido |
| **Colores** | Círculos de color en la ficha. Viajan en el carrito y en el mensaje de WhatsApp |

Los talles llevan el stock; los colores son una elección que acompaña al pedido.

## Cómo funciona un pedido

1. La persona toca **Lo quiero** (se registra el click) y elige talle.
2. En el carrito pone su nombre, elige cómo va a pagar y toca **Finalizar por WhatsApp**.
3. El servidor crea el pedido (`LP-AAMM-NNN`), **descuenta el stock** del talle y arma el mensaje de WhatsApp con el detalle.
4. En el panel, el pedido aparece como *pendiente*. Al confirmarlo o entregarlo se mantiene el stock descontado; al cancelarlo, el stock vuelve.

## Fotos

Cualquier foto (JPG, PNG, WEBP, HEIC de iPhone, de cualquier tamaño y orientación) se convierte a 1200×1600 px. La **tabla de talles** es la excepción: conserva su proporción (solo se limita el lado largo a 1600 px) porque son números que tienen que leerse.

Dos modos para las fotos de producto:

- **Recortar al centro** (por defecto): rellena el marco, la grilla queda pareja.
- **Encajar completa**: no recorta nada, rellena con fondo claro.

Se guarda el original, así que desde el panel se puede reprocesar cada foto en el otro modo.

## Métricas que registra

`view_product`, `add_to_cart` (click en *Lo quiero*), `remove_from_cart`, `open_cart`, `checkout_whatsapp` (pedido enviado), `whatsapp_float`, `whatsapp_hero`, `whatsapp_product`. Se ven en **Resumen** del panel, por día y por prenda.

## Estructura de la tienda

Calcada de elcamarin.com a pedido de Franco: header de tres filas (anuncio, logo centrado, menú) → slider a todo el ancho → dos banners de categoría → grilla con barra lateral de filtros (categoría, talle, precio) y orden → nosotras → cómo comprar → footer de tres columnas con newsletter. Los emails del newsletter se guardan en la tabla `subscribers` (endpoint `/api/admin/subscribers`).
Las categorías del menú, los filtros y el footer salen solas del campo **Categoría** de cada prenda en el panel: si se crea una prenda con categoría "VESTIDOS", aparece en el menú.
Cada prenda abre en una ficha (vista rápida) con su URL propia (`#p/slug`) para compartir por WhatsApp o Instagram.

Las fotos son reales de Lopiana: cuadros extraídos de los reels de @lopiana.clothes (los cuatro reels en 1080p dan las mejores). Nombres y precios vienen de la home de lopianaclothes.com; la correspondencia foto ↔ nombre es aproximada y la clienta la corrige desde el panel, donde también sube sus fotos originales.

## Seguridad

Pensado para estar expuesto a internet, no solo en la red de casa:

- El PIN se guarda hasheado con scrypt, nunca en claro. Mínimo 6 caracteres, y se rechazan los obvios.
- La sesión es un token aleatorio guardado en la base con vencimiento a 14 días. Cambiar el PIN
  cierra todas las sesiones abiertas en otros dispositivos.
- Seis intentos fallidos desde una IP la bloquean 15 minutos: un PIN corto deja de ser reventable.
- Cuota por IP en lo público: 6 pedidos/hora, 5 suscripciones cada 10 min, 120 eventos/min.
  Un pedido descuenta stock real, así que es lo más caro que puede hacer un anónimo.
- CSP, HSTS, nosniff, X-Frame-Options y Referrer-Policy en toda respuesta.
- Con `LOPIANA_HOSTS` definido, solo se responde a esos dominios.
- Las subidas se validan como imágenes reales y se cortan en 25 MB y 60 megapíxeles.

Si se pierde el PIN: borrar la fila `admin_pin_hash` de la tabla `settings` y reiniciar.

## Mobile

La tienda y el panel se usan desde el celular:

- **Tienda**: galería a lo ancho, barra fija con precio y *Agregar*, filtros en un panel que se
  abre a pedido, carrito a pantalla completa, talles y colores con área táctil de 44 px o más.
- **Panel**: barra inferior de cuatro secciones en vez de la lateral, editor a pantalla completa
  con el botón de guardar siempre a mano, listas en tarjetas en vez de tablas.
- Todos los campos van en 16 px: por debajo de eso iOS hace zoom solo al tocarlos.
