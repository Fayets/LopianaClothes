"""Lopiana Clothes · landing + carrito a WhatsApp + panel de gestión local."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import images as imgproc
from . import security as sec
from .db import BASE_DIR, get_db, get_settings, init_db, rows, set_setting

MEDIA_DIR = BASE_DIR / "media"
PRODUCTS_MEDIA = MEDIA_DIR / "products"
ORIGINALS_DIR = MEDIA_DIR / "originals"
STATIC_DIR = BASE_DIR / "static"
COOKIE = "lopiana_admin"

# En el VPS se sirve por HTTPS detrás de un proxy: la cookie va marcada Secure y solo
# se aceptan los dominios declarados. En local queda todo abierto para poder probar.
PUBLIC_HOSTS = [h.strip() for h in os.environ.get("LOPIANA_HOSTS", "").split(",") if h.strip()]
HTTPS_ONLY = os.environ.get("LOPIANA_HTTPS", "0") == "1"
MAX_UPLOAD_MB = 25

app = FastAPI(title="Lopiana Clothes", docs_url=None, redoc_url=None, openapi_url=None)
ASSET_VERSION = str(int(datetime.now().timestamp()))

if PUBLIC_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=PUBLIC_HOSTS + ["localhost", "127.0.0.1"])


CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self' https://wa.me; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


@app.middleware("http")
async def headers_and_cache(request: Request, call_next):
    """Cabeceras de seguridad + evitar que el navegador se quede con CSS/JS/fotos viejas."""
    if request.method in ("POST", "PUT", "DELETE"):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > (MAX_UPLOAD_MB + 5) * 1024 * 1024:
            return Response("Archivo demasiado grande", status_code=413)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
    response.headers["Content-Security-Policy"] = CSP
    if HTTPS_ONLY:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/admin") or request.url.path == "/admin":
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith(("/static", "/media")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.on_event("startup")
def _startup() -> None:
    init_db()
    PRODUCTS_MEDIA.mkdir(parents=True, exist_ok=True)
    ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- helpers
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "producto"


def money(v: float) -> str:
    return "$ " + f"{v:,.0f}".replace(",", ".")


def transfer_price_for(p: dict, settings: dict) -> float:
    if p.get("transfer_price") not in (None, "", 0):
        return float(p["transfer_price"])
    pct = float(settings.get("transfer_discount_pct") or 0)
    return round(float(p["price"]) * (1 - pct / 100))


def load_products(con, only_active: bool = True, product_id: Optional[int] = None, slug: Optional[str] = None) -> list[dict]:
    settings = get_settings(con)
    q = "SELECT * FROM products WHERE 1=1"
    args: list = []
    if only_active:
        q += " AND active = 1"
    if product_id is not None:
        q += " AND id = ?"
        args.append(product_id)
    if slug is not None:
        q += " AND slug = ?"
        args.append(slug)
    q += " ORDER BY sort_order, id"
    prods = rows(con.execute(q, args))
    for p in prods:
        pics = [
            {**im, "url": f"/media/products/{p['id']}/{im['filename']}", "thumb_url": f"/media/products/{p['id']}/{im['thumb']}"}
            for im in rows(con.execute("SELECT * FROM product_images WHERE product_id = ? ORDER BY position, id", (p["id"],)))
        ]
        # La primera de la galería es la principal: es la que sale en la grilla y abre la ficha.
        p["images"] = [im for im in pics if im.get("kind", "gallery") != "size_chart"]
        chart = next((im for im in pics if im.get("kind") == "size_chart"), None)
        p["size_chart"] = chart
        p["main_image"] = p["images"][0] if p["images"] else None
        p["sizes"] = rows(con.execute("SELECT id, size, stock, position FROM product_sizes WHERE product_id = ? ORDER BY position, id", (p["id"],)))
        p["colors"] = rows(con.execute("SELECT id, name, hex, position FROM product_colors WHERE product_id = ? ORDER BY position, id", (p["id"],)))
        p["transfer_price_final"] = transfer_price_for(p, settings)
        p["discount_pct"] = round((1 - p["transfer_price_final"] / p["price"]) * 100) if p["price"] else 0
        p["total_stock"] = sum(s["stock"] for s in p["sizes"])
    return prods


def public_settings(settings: dict) -> dict:
    keys = ["brand_name", "whatsapp_number", "transfer_discount_pct", "banner_text", "address", "instagram", "email", "size_chart_note"]
    return {k: settings.get(k, "") for k in keys}


# ---------------------------------------------------------------- auth admin
def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token,
        httponly=True,
        secure=HTTPS_ONLY,
        samesite="lax",
        max_age=60 * 60 * 24 * sec.SESSION_DAYS,
        path="/",
    )


def require_admin(request: Request):
    token = request.cookies.get(COOKIE, "")
    with get_db() as con:
        if not sec.session_valid(con, token):
            raise HTTPException(401, "No autorizado")
    return True


class LoginIn(BaseModel):
    pin: str


class NewPinIn(BaseModel):
    current_pin: str = ""
    new_pin: str


@app.post("/api/admin/login")
def admin_login(body: LoginIn, request: Request, response: Response):
    ip = sec.client_ip(request)
    # Ojo: el intento fallido se confirma en su propia transacción. Si se registrara en la
    # misma que termina en HTTPException, el rollback lo borraría y el bloqueo nunca subiría.
    with get_db() as con:
        locked = sec.login_locked_for(con, ip)
    if locked:
        raise HTTPException(429, f"Demasiados intentos fallidos. Probá de nuevo en {locked // 60 + 1} min.")

    with get_db() as con:
        s = get_settings(con)
        ok = sec.verify_pin(body.pin.strip(), s.get("admin_pin_hash", ""))
        sec.record_login(con, ip, ok)
        if ok:
            token = sec.issue_session(con, ip, request.headers.get("user-agent", ""))
            must_change = s.get("pin_is_default", "0") == "1"
    if not ok:
        raise HTTPException(401, "PIN incorrecto")
    _set_cookie(response, token)
    return {"ok": True, "must_change_pin": must_change}


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response):
    with get_db() as con:
        sec.revoke_session(con, request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/admin/me")
def admin_me(_: bool = Depends(require_admin)):
    with get_db() as con:
        s = get_settings(con)
    return {"ok": True, "must_change_pin": s.get("pin_is_default", "0") == "1"}


@app.post("/api/admin/pin")
def admin_change_pin(body: NewPinIn, request: Request, response: Response, _: bool = Depends(require_admin)):
    """Cambiar el PIN cierra todas las sesiones abiertas y deja viva solo la de acá."""
    new = body.new_pin.strip()
    problem = sec.pin_problem(new)
    if problem:
        raise HTTPException(400, problem)
    with get_db() as con:
        s = get_settings(con)
        if s.get("pin_is_default", "0") != "1" and not sec.verify_pin(body.current_pin.strip(), s.get("admin_pin_hash", "")):
            raise HTTPException(401, "El PIN actual no es correcto.")
        set_setting(con, "admin_pin_hash", sec.hash_pin(new))
        set_setting(con, "pin_is_default", "0")
        sec.revoke_all_sessions(con)
        token = sec.issue_session(con, sec.client_ip(request), request.headers.get("user-agent", ""))
    _set_cookie(response, token)
    return {"ok": True}


# ---------------------------------------------------------------- público
@app.get("/api/settings/public")
def api_public_settings():
    with get_db() as con:
        return public_settings(get_settings(con))


@app.get("/api/products")
def api_products():
    with get_db() as con:
        return load_products(con)


@app.get("/api/products/{slug}")
def api_product(slug: str):
    with get_db() as con:
        ps = load_products(con, slug=slug)
    if not ps:
        raise HTTPException(404, "Producto no encontrado")
    return ps[0]


class EventIn(BaseModel):
    type: str = Field(pattern=r"^[a-z_]{2,40}$")
    product_id: Optional[int] = None
    size: Optional[str] = None
    session_id: Optional[str] = None
    meta: Optional[dict] = None


@app.post("/api/events")
def api_event(body: EventIn, request: Request):
    sec.rate_limit(request, "events", limit=120, seconds=60)
    with get_db() as con:
        con.execute(
            "INSERT INTO events(type, product_id, size, session_id, meta) VALUES (?,?,?,?,?)",
            (body.type, body.product_id, body.size, body.session_id, json.dumps(body.meta or {}, ensure_ascii=False)),
        )
    return {"ok": True}


class NewsletterIn(BaseModel):
    email: str
    session_id: Optional[str] = None


@app.post("/api/newsletter")
def api_newsletter(body: NewsletterIn, request: Request):
    sec.rate_limit(request, "news", limit=5, seconds=600)
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Email inválido")
    with get_db() as con:
        con.execute("INSERT OR IGNORE INTO subscribers(email, session_id) VALUES (?, ?)", (email, body.session_id))
        con.execute("INSERT INTO events(type, session_id) VALUES (?, ?)", ("newsletter", body.session_id))
    return {"ok": True}


@app.get("/api/admin/subscribers")
def admin_subscribers(_: bool = Depends(require_admin)):
    with get_db() as con:
        return rows(con.execute("SELECT * FROM subscribers ORDER BY id DESC"))


class OrderItemIn(BaseModel):
    product_id: int
    size: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=40)
    qty: int = Field(ge=1, le=20)


class OrderIn(BaseModel):
    items: list[OrderItemIn]
    customer_name: str = Field(default="", max_length=80)
    customer_phone: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=500)
    payment: str = "transferencia"
    session_id: Optional[str] = Field(default=None, max_length=64)


def _next_code(con) -> str:
    n = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] + 1
    return f"LP-{datetime.now():%y%m}-{n:03d}"


def _build_whatsapp_url(settings: dict, order: dict, items: list[dict]) -> str:
    lines = [settings.get("whatsapp_greeting", "Hola! Quiero hacer este pedido:"), ""]
    for it in items:
        detalle = "".join([
            f" · Talle {it['size']}" if it.get("size") else "",
            f" · {it['color']}" if it.get("color") else "",
        ])
        lines.append(f"• {it['qty']} x {it['product_name']}{detalle} — {money(it['unit_price'] * it['qty'])}")
    lines.append("")
    lines.append(f"Pago: {order['payment']}")
    lines.append(f"Total: {money(order['total'])}")
    if order.get("customer_name"):
        lines.append(f"Nombre: {order['customer_name']}")
    lines.append(f"Pedido N° {order['code']}")
    text = "\n".join(lines)
    return f"https://wa.me/{settings['whatsapp_number']}?text={quote(text)}"


@app.post("/api/orders")
def api_create_order(body: OrderIn, request: Request):
    # Un pedido descuenta stock real: es lo más caro que puede hacer un anónimo.
    sec.rate_limit(request, "orders", limit=6, seconds=3600)
    if not body.items:
        raise HTTPException(400, "El carrito está vacío")
    if len(body.items) > 20:
        raise HTTPException(400, "Demasiadas prendas en un mismo pedido")
    payment = body.payment if body.payment in ("transferencia", "efectivo", "otro") else "otro"
    with get_db() as con:
        settings = get_settings(con)
        con.execute("BEGIN IMMEDIATE")
        items_out: list[dict] = []
        subtotal = total = 0.0
        for it in body.items:
            ps = load_products(con, product_id=it.product_id)
            if not ps:
                raise HTTPException(400, "Producto no disponible")
            p = ps[0]
            unit_list = float(p["price"])
            unit = p["transfer_price_final"] if payment in ("transferencia", "efectivo") else unit_list
            if p["sizes"]:
                size_row = next((s for s in p["sizes"] if s["size"] == it.size), None)
                if not size_row:
                    raise HTTPException(400, f"Elegí un talle para {p['name']}")
                if size_row["stock"] < it.qty:
                    raise HTTPException(409, f"No hay stock suficiente de {p['name']} talle {it.size} (quedan {size_row['stock']})")
                con.execute("UPDATE product_sizes SET stock = stock - ? WHERE id = ?", (it.qty, size_row["id"]))
            color = None
            if p["colors"]:
                color = next((c["name"] for c in p["colors"] if c["name"] == it.color), None)
                if not color:
                    raise HTTPException(400, f"Elegí un color para {p['name']}")
            items_out.append({"product_id": p["id"], "product_name": p["name"], "size": it.size if p["sizes"] else None,
                              "color": color, "qty": it.qty, "unit_price": unit, "list_price": unit_list})
            subtotal += unit_list * it.qty
            total += unit * it.qty
        code = _next_code(con)
        cur = con.execute(
            "INSERT INTO orders(code, customer_name, customer_phone, note, payment, status, subtotal, total, session_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (code, body.customer_name.strip()[:80], body.customer_phone.strip()[:40], body.note.strip()[:500], payment, "pendiente", subtotal, total, body.session_id),
        )
        oid = cur.lastrowid
        for it in items_out:
            con.execute(
                "INSERT INTO order_items(order_id, product_id, product_name, size, color, qty, unit_price, list_price) VALUES (?,?,?,?,?,?,?,?)",
                (oid, it["product_id"], it["product_name"], it["size"], it["color"], it["qty"], it["unit_price"], it["list_price"]),
            )
            con.execute("INSERT INTO stock_moves(product_id, size, delta, reason, order_id) VALUES (?,?,?,?,?)", (it["product_id"], it["size"], -it["qty"], "pedido", oid))
        con.execute("INSERT INTO events(type, session_id, meta) VALUES (?,?,?)", ("checkout_whatsapp", body.session_id, json.dumps({"order_id": oid, "code": code, "total": total})))
        order = {"id": oid, "code": code, "payment": payment, "total": total, "customer_name": body.customer_name.strip()}
        url = _build_whatsapp_url(settings, order, items_out)
    return {"ok": True, "order": order, "items": items_out, "whatsapp_url": url}


# ---------------------------------------------------------------- admin: stats
@app.get("/api/admin/stats")
def admin_stats(days: int = 30, month: Optional[str] = None, _: bool = Depends(require_admin)):
    """Métricas del período: últimos N días, o un mes puntual (month=AAAA-MM)."""
    if month and re.fullmatch(r"\d{4}-\d{2}", month):
        y, m = int(month[:4]), int(month[5:])
        since = f"{y:04d}-{m:02d}-01 00:00:00"
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        until = f"{ny:04d}-{nm:02d}-01 00:00:00"
    else:
        month = None
        since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
        until = "9999-12-31 00:00:00"
    rng = (since, until)
    with get_db() as con:
        by_type = {r["type"]: r["n"] for r in con.execute("SELECT type, COUNT(*) n FROM events WHERE created_at >= ? AND created_at < ? GROUP BY type", rng)}
        orders_by_status = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) n FROM orders WHERE created_at >= ? AND created_at < ? GROUP BY status", rng)}
        revenue = con.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE created_at >= ? AND created_at < ? AND status IN ('confirmado','entregado')", rng).fetchone()[0]
        pending_total = con.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE created_at >= ? AND created_at < ? AND status = 'pendiente'", rng).fetchone()[0]
        per_product = rows(con.execute(
            """SELECT p.id, p.name,
                      SUM(CASE WHEN e.type='add_to_cart' THEN 1 ELSE 0 END) AS lo_quiero,
                      SUM(CASE WHEN e.type='view_product' THEN 1 ELSE 0 END) AS vistas
               FROM products p LEFT JOIN events e ON e.product_id = p.id AND e.created_at >= ? AND e.created_at < ?
               GROUP BY p.id ORDER BY lo_quiero DESC, vistas DESC""", rng))
        sold = {r["product_id"]: r["n"] for r in con.execute(
            "SELECT oi.product_id, SUM(oi.qty) n FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE o.created_at >= ? AND o.created_at < ? AND o.status != 'cancelado' GROUP BY oi.product_id", rng)}
        for pp in per_product:
            pp["vendidos"] = sold.get(pp["id"], 0)
        daily = rows(con.execute(
            """SELECT substr(created_at,1,10) AS day,
                      SUM(CASE WHEN type='add_to_cart' THEN 1 ELSE 0 END) AS lo_quiero,
                      SUM(CASE WHEN type='checkout_whatsapp' THEN 1 ELSE 0 END) AS whatsapp,
                      SUM(CASE WHEN type='view_product' THEN 1 ELSE 0 END) AS vistas
               FROM events WHERE created_at >= ? AND created_at < ? GROUP BY day ORDER BY day""", rng))
        sessions = con.execute("SELECT COUNT(DISTINCT session_id) FROM events WHERE created_at >= ? AND created_at < ? AND session_id IS NOT NULL", rng).fetchone()[0]
        low_stock = rows(con.execute("SELECT p.name, s.size, s.stock FROM product_sizes s JOIN products p ON p.id = s.product_id WHERE s.stock <= 1 ORDER BY s.stock, p.name"))
        first_event = con.execute("SELECT MIN(substr(created_at,1,7)) FROM events").fetchone()[0]
        subscribers = con.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    lo_quiero = by_type.get("add_to_cart", 0)
    wa = by_type.get("checkout_whatsapp", 0)
    return {
        "days": days,
        "month": month,
        "since": since[:10],
        "first_month": first_event or datetime.now().strftime("%Y-%m"),
        "visitas": sessions,
        "vistas_producto": by_type.get("view_product", 0),
        "lo_quiero": lo_quiero,
        "whatsapp": wa,
        "whatsapp_flotante": by_type.get("whatsapp_float", 0),
        "suscriptores": subscribers,
        "conversion_lo_quiero_a_whatsapp": round(wa / lo_quiero * 100, 1) if lo_quiero else 0,
        "orders_by_status": orders_by_status,
        "revenue": revenue,
        "pending_total": pending_total,
        "per_product": per_product,
        "daily": daily,
        "low_stock": low_stock,
    }


@app.get("/api/admin/events")
def admin_events(limit: int = 100, _: bool = Depends(require_admin)):
    with get_db() as con:
        return rows(con.execute(
            "SELECT e.*, p.name AS product_name FROM events e LEFT JOIN products p ON p.id = e.product_id ORDER BY e.id DESC LIMIT ?", (min(limit, 500),)))


# ---------------------------------------------------------------- admin: productos
class SizeIn(BaseModel):
    size: str = Field(max_length=20)
    stock: int = Field(ge=0, le=9999)


class ColorIn(BaseModel):
    name: str = Field(max_length=40)
    hex: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="", max_length=60)
    price: float = Field(ge=0, le=99_999_999)
    transfer_price: Optional[float] = Field(default=None, ge=0, le=99_999_999)
    active: bool = True
    sizes: list[SizeIn] = Field(default=[], max_length=40)
    colors: list[ColorIn] = Field(default=[], max_length=30)


@app.get("/api/admin/products")
def admin_products(_: bool = Depends(require_admin)):
    with get_db() as con:
        return load_products(con, only_active=False)


@app.post("/api/admin/products")
def admin_create_product(body: ProductIn, _: bool = Depends(require_admin)):
    with get_db() as con:
        base = slugify(body.name)
        slug, i = base, 2
        while con.execute("SELECT 1 FROM products WHERE slug = ?", (slug,)).fetchone():
            slug, i = f"{base}-{i}", i + 1
        order = (con.execute("SELECT COALESCE(MAX(sort_order),0) FROM products").fetchone()[0] or 0) + 1
        cur = con.execute(
            "INSERT INTO products(slug, name, description, category, price, transfer_price, active, sort_order) VALUES (?,?,?,?,?,?,?,?)",
            (slug, body.name.strip(), body.description, body.category.strip(), body.price, body.transfer_price or None, int(body.active), order),
        )
        pid = cur.lastrowid
        _save_sizes(con, pid, body.sizes)
        _save_colors(con, pid, body.colors)
        return load_products(con, only_active=False, product_id=pid)[0]


def _save_sizes(con, pid: int, sizes: list[SizeIn]) -> None:
    existing = {r["size"]: dict(r) for r in con.execute("SELECT * FROM product_sizes WHERE product_id = ?", (pid,))}
    keep = set()
    for pos, s in enumerate(sizes):
        name = s.size.strip().upper()
        if not name:
            continue
        keep.add(name)
        if name in existing:
            delta = s.stock - existing[name]["stock"]
            con.execute("UPDATE product_sizes SET stock = ?, position = ? WHERE id = ?", (s.stock, pos, existing[name]["id"]))
            if delta:
                con.execute("INSERT INTO stock_moves(product_id, size, delta, reason) VALUES (?,?,?,?)", (pid, name, delta, "ajuste manual"))
        else:
            con.execute("INSERT INTO product_sizes(product_id, size, stock, position) VALUES (?,?,?,?)", (pid, name, s.stock, pos))
            if s.stock:
                con.execute("INSERT INTO stock_moves(product_id, size, delta, reason) VALUES (?,?,?,?)", (pid, name, s.stock, "alta"))
    for name, row in existing.items():
        if name not in keep:
            con.execute("DELETE FROM product_sizes WHERE id = ?", (row["id"],))


def _save_colors(con, pid: int, colors: list[ColorIn]) -> None:
    """Los colores son una elección que viaja con el pedido; el stock lo llevan los talles."""
    con.execute("DELETE FROM product_colors WHERE product_id = ?", (pid,))
    seen = set()
    for pos, c in enumerate(colors):
        name = c.name.strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        con.execute("INSERT INTO product_colors(product_id, name, hex, position) VALUES (?,?,?,?)", (pid, name, c.hex.lower(), pos))


@app.put("/api/admin/products/{pid}")
def admin_update_product(pid: int, body: ProductIn, _: bool = Depends(require_admin)):
    with get_db() as con:
        if not con.execute("SELECT 1 FROM products WHERE id = ?", (pid,)).fetchone():
            raise HTTPException(404, "No existe")
        con.execute(
            "UPDATE products SET name=?, description=?, category=?, price=?, transfer_price=?, active=?, updated_at=datetime('now','localtime') WHERE id=?",
            (body.name.strip(), body.description, body.category.strip(), body.price, body.transfer_price or None, int(body.active), pid),
        )
        _save_sizes(con, pid, body.sizes)
        _save_colors(con, pid, body.colors)
        return load_products(con, only_active=False, product_id=pid)[0]


@app.delete("/api/admin/products/{pid}")
def admin_delete_product(pid: int, _: bool = Depends(require_admin)):
    with get_db() as con:
        con.execute("DELETE FROM products WHERE id = ?", (pid,))
    folder = PRODUCTS_MEDIA / str(pid)  # si no, las fotos quedan ocupando disco para siempre
    if folder.is_dir():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        folder.rmdir()
    return {"ok": True}


class ReorderIn(BaseModel):
    ids: list[int]


@app.put("/api/admin/products/reorder")
def admin_reorder_products(body: ReorderIn, _: bool = Depends(require_admin)):
    with get_db() as con:
        for pos, pid in enumerate(body.ids):
            con.execute("UPDATE products SET sort_order = ? WHERE id = ?", (pos, pid))
    return {"ok": True}


@app.post("/api/admin/products/{pid}/images")
async def admin_upload_images(pid: int, files: list[UploadFile] = File(...), mode: str = Form("cover"), _: bool = Depends(require_admin)):
    with get_db() as con:
        if not con.execute("SELECT 1 FROM products WHERE id = ?", (pid,)).fetchone():
            raise HTTPException(404, "No existe")
        settings = get_settings(con)
        w, h = int(settings.get("image_width", 1200)), int(settings.get("image_height", 1600))
        mode = mode if mode in ("cover", "contain") else settings.get("image_mode", "cover")
        pos = (con.execute("SELECT COALESCE(MAX(position),-1) FROM product_images WHERE product_id = ? AND kind = 'gallery'", (pid,)).fetchone()[0]) + 1
        out = []
        for f in files:
            data = await f.read()
            if len(data) > 25 * 1024 * 1024:
                raise HTTPException(413, f"{f.filename}: la foto pesa más de 25 MB")
            try:
                info = imgproc.process_upload(data, f.filename or "foto.jpg", PRODUCTS_MEDIA / str(pid), ORIGINALS_DIR, w, h, mode)
            except ValueError as e:
                raise HTTPException(400, str(e))
            except Exception as e:  # imagen corrupta
                raise HTTPException(400, f"{f.filename}: no se pudo leer la imagen ({e})")
            cur = con.execute(
                "INSERT INTO product_images(product_id, filename, thumb, original, width, height, position, kind) VALUES (?,?,?,?,?,?,?,'gallery')",
                (pid, info["filename"], info["thumb"], info["original"], info["width"], info["height"], pos),
            )
            pos += 1
            out.append({"id": cur.lastrowid, **info, "url": f"/media/products/{pid}/{info['filename']}", "thumb_url": f"/media/products/{pid}/{info['thumb']}"})
        return out


@app.delete("/api/admin/images/{iid}")
def admin_delete_image(iid: int, _: bool = Depends(require_admin)):
    with get_db() as con:
        row = con.execute("SELECT * FROM product_images WHERE id = ?", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, "No existe")
        for name in (row["filename"], row["thumb"]):
            p = PRODUCTS_MEDIA / str(row["product_id"]) / name
            if p.exists():
                p.unlink()
        con.execute("DELETE FROM product_images WHERE id = ?", (iid,))
    return {"ok": True}


class ImageOrderIn(BaseModel):
    ids: list[int]


@app.put("/api/admin/products/{pid}/images/reorder")
def admin_reorder_images(pid: int, body: ImageOrderIn, _: bool = Depends(require_admin)):
    with get_db() as con:
        for pos, iid in enumerate(body.ids):
            con.execute("UPDATE product_images SET position = ? WHERE id = ? AND product_id = ?", (pos, iid, pid))
    return {"ok": True}


@app.put("/api/admin/images/{iid}/main")
def admin_set_main_image(iid: int, _: bool = Depends(require_admin)):
    """La foto principal es, simplemente, la primera de la galería: la que se ve en la
    grilla de la tienda y la que abre la ficha. Este endpoint la manda al frente."""
    with get_db() as con:
        row = con.execute("SELECT * FROM product_images WHERE id = ? AND kind = 'gallery'", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, "No existe")
        others = [r["id"] for r in con.execute(
            "SELECT id FROM product_images WHERE product_id = ? AND kind = 'gallery' AND id != ? ORDER BY position, id",
            (row["product_id"], iid))]
        con.execute("UPDATE product_images SET position = 0 WHERE id = ?", (iid,))
        for pos, other in enumerate(others, start=1):
            con.execute("UPDATE product_images SET position = ? WHERE id = ?", (pos, other))
        return load_products(con, only_active=False, product_id=row["product_id"])[0]


@app.post("/api/admin/products/{pid}/size-chart")
async def admin_upload_size_chart(pid: int, file: UploadFile = File(...), _: bool = Depends(require_admin)):
    """Foto de la tabla de talles. No se recorta: se respeta su proporción para que se lea."""
    with get_db() as con:
        if not con.execute("SELECT 1 FROM products WHERE id = ?", (pid,)).fetchone():
            raise HTTPException(404, "No existe")
        data = await file.read()
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"La foto pesa más de {MAX_UPLOAD_MB} MB")
        try:
            info = imgproc.process_size_chart(data, file.filename or "talles.jpg", PRODUCTS_MEDIA / str(pid), ORIGINALS_DIR)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(400, f"No se pudo leer la imagen ({e})")
        _drop_size_chart(con, pid)
        con.execute(
            "INSERT INTO product_images(product_id, filename, thumb, original, width, height, position, kind) VALUES (?,?,?,?,?,?,-1,'size_chart')",
            (pid, info["filename"], info["thumb"], info["original"], info["width"], info["height"]),
        )
        return load_products(con, only_active=False, product_id=pid)[0]


@app.delete("/api/admin/products/{pid}/size-chart")
def admin_delete_size_chart(pid: int, _: bool = Depends(require_admin)):
    with get_db() as con:
        _drop_size_chart(con, pid)
        return load_products(con, only_active=False, product_id=pid)[0]


def _drop_size_chart(con, pid: int) -> None:
    for row in con.execute("SELECT * FROM product_images WHERE product_id = ? AND kind = 'size_chart'", (pid,)).fetchall():
        for name in (row["filename"], row["thumb"]):
            (PRODUCTS_MEDIA / str(pid) / name).unlink(missing_ok=True)
        con.execute("DELETE FROM product_images WHERE id = ?", (row["id"],))


@app.post("/api/admin/images/{iid}/reprocess")
def admin_reprocess_image(iid: int, mode: str = Form("cover"), _: bool = Depends(require_admin)):
    with get_db() as con:
        row = con.execute("SELECT * FROM product_images WHERE id = ?", (iid,)).fetchone()
        if not row or not row["original"]:
            raise HTTPException(404, "No hay original guardado")
        settings = get_settings(con)
        w, h = int(settings.get("image_width", 1200)), int(settings.get("image_height", 1600))
        imgproc.reprocess(ORIGINALS_DIR / row["original"], PRODUCTS_MEDIA / str(row["product_id"]), w, h, mode, row["filename"], row["thumb"])
    return {"ok": True}


# ---------------------------------------------------------------- admin: pedidos
ORDER_STATUSES = ("pendiente", "confirmado", "entregado", "cancelado")


@app.get("/api/admin/orders")
def admin_orders(status: Optional[str] = None, _: bool = Depends(require_admin)):
    with get_db() as con:
        q, args = "SELECT * FROM orders", []
        if status in ORDER_STATUSES:
            q += " WHERE status = ?"
            args.append(status)
        q += " ORDER BY id DESC LIMIT 500"
        orders = rows(con.execute(q, args))
        for o in orders:
            o["items"] = rows(con.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (o["id"],)))
        return orders


class StatusIn(BaseModel):
    status: str


@app.put("/api/admin/orders/{oid}/status")
def admin_order_status(oid: int, body: StatusIn, _: bool = Depends(require_admin)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(400, "Estado inválido")
    with get_db() as con:
        o = con.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if not o:
            raise HTTPException(404, "No existe")
        old = o["status"]
        items = rows(con.execute("SELECT * FROM order_items WHERE order_id = ?", (oid,)))
        # cancelar devuelve el stock; reactivar un cancelado lo vuelve a descontar
        if body.status == "cancelado" and old != "cancelado":
            for it in items:
                if it["size"]:
                    con.execute("UPDATE product_sizes SET stock = stock + ? WHERE product_id = ? AND size = ?", (it["qty"], it["product_id"], it["size"]))
                    con.execute("INSERT INTO stock_moves(product_id, size, delta, reason, order_id) VALUES (?,?,?,?,?)", (it["product_id"], it["size"], it["qty"], "pedido cancelado", oid))
        elif old == "cancelado" and body.status != "cancelado":
            for it in items:
                if it["size"]:
                    con.execute("UPDATE product_sizes SET stock = MAX(0, stock - ?) WHERE product_id = ? AND size = ?", (it["qty"], it["product_id"], it["size"]))
                    con.execute("INSERT INTO stock_moves(product_id, size, delta, reason, order_id) VALUES (?,?,?,?,?)", (it["product_id"], it["size"], -it["qty"], "pedido reactivado", oid))
        con.execute("UPDATE orders SET status = ?, updated_at = datetime('now','localtime') WHERE id = ?", (body.status, oid))
    return {"ok": True}


class OrderNoteIn(BaseModel):
    note: str = ""
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


@app.put("/api/admin/orders/{oid}")
def admin_order_update(oid: int, body: OrderNoteIn, _: bool = Depends(require_admin)):
    with get_db() as con:
        o = con.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if not o:
            raise HTTPException(404, "No existe")
        con.execute(
            "UPDATE orders SET note = ?, customer_name = COALESCE(?, customer_name), customer_phone = COALESCE(?, customer_phone), updated_at = datetime('now','localtime') WHERE id = ?",
            (body.note, body.customer_name, body.customer_phone, oid),
        )
    return {"ok": True}


@app.get("/api/admin/stock-moves")
def admin_stock_moves(limit: int = 100, _: bool = Depends(require_admin)):
    with get_db() as con:
        return rows(con.execute(
            "SELECT m.*, p.name AS product_name, o.code AS order_code FROM stock_moves m LEFT JOIN products p ON p.id = m.product_id LEFT JOIN orders o ON o.id = m.order_id ORDER BY m.id DESC LIMIT ?", (min(limit, 500),)))


# ---------------------------------------------------------------- admin: ajustes
EDITABLE_SETTINGS = ("brand_name", "whatsapp_number", "whatsapp_greeting", "transfer_discount_pct",
                     "banner_text", "address", "instagram", "email", "image_mode", "size_chart_note")


@app.get("/api/admin/settings")
def admin_get_settings(_: bool = Depends(require_admin)):
    with get_db() as con:
        s = get_settings(con)
    return {k: s.get(k, "") for k in EDITABLE_SETTINGS}


@app.put("/api/admin/settings")
def admin_put_settings(body: dict, _: bool = Depends(require_admin)):
    with get_db() as con:
        for k, v in body.items():
            if k in EDITABLE_SETTINGS and v is not None:
                v = str(v).strip()
                if k == "whatsapp_number":
                    v = re.sub(r"\D", "", v)
                set_setting(con, k, v)
    return {"ok": True}


# ---------------------------------------------------------------- páginas y estáticos
def _page(name: str) -> Response:
    html = (STATIC_DIR / name).read_text(encoding="utf-8").replace("{{v}}", ASSET_VERSION)
    return Response(html, media_type="text/html; charset=utf-8")


@app.get("/")
def page_index():
    return _page("index.html")


@app.get("/p/{slug}")
def page_product(slug: str):
    return _page("index.html")


@app.get("/admin")
def page_admin():
    return _page("admin.html")


@app.get("/admin/")
def page_admin_slash():
    return RedirectResponse("/admin")


app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
