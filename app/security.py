"""Autenticación del panel y frenos contra abuso.

Lo que resuelve este módulo, en orden de importancia:

1. El PIN nunca se guarda en claro: va hasheado con scrypt.
2. La sesión no se deduce del PIN. Al entrar se emite un token aleatorio que vive en
   la tabla `sessions` con vencimiento. Cerrar sesión o cambiar el PIN los invalida.
3. El login tiene límite de intentos por IP: un PIN de 6 dígitos deja de ser
   reventable por fuerza bruta desde internet.
4. Los endpoints públicos (eventos, newsletter, pedidos) tienen cuota por IP para que
   nadie infle las métricas ni vacíe el stock con pedidos falsos.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

# --- política -----------------------------------------------------------------
PIN_MIN_LEN = 6
SESSION_DAYS = 14
LOGIN_MAX_FAILS = 6          # por IP
LOGIN_WINDOW_MIN = 15        # ventana de conteo
LOGIN_LOCK_MIN = 15          # cuánto queda bloqueada la IP

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


# --- PIN ----------------------------------------------------------------------
def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, dk_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(dk_hex) // 2)
    except Exception:
        return False
    return hmac.compare_digest(dk.hex(), dk_hex)


def pin_problem(pin: str) -> str | None:
    """Devuelve el motivo por el que un PIN no sirve, o None si está bien."""
    pin = pin.strip()
    if len(pin) < PIN_MIN_LEN:
        return f"El PIN tiene que tener al menos {PIN_MIN_LEN} caracteres."
    if pin in ("123456", "000000", "111111", "123123", "654321", "112233"):
        return "Ese PIN es de los primeros que prueba cualquiera. Elegí otro."
    if len(set(pin)) == 1:
        return "No uses el mismo carácter repetido."
    if pin.isdigit() and (pin in "01234567890" or pin in "09876543210"):
        return "No uses dígitos consecutivos."
    return None


# --- sesiones -----------------------------------------------------------------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(con, ip: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    con.execute(
        "INSERT INTO sessions(token_hash, expires_at, ip, user_agent) VALUES (?,?,?,?)",
        (_token_hash(token), expires, ip, (user_agent or "")[:200]),
    )
    con.execute("DELETE FROM sessions WHERE expires_at < datetime('now','localtime')")
    return token


def session_valid(con, token: str) -> bool:
    if not token:
        return False
    row = con.execute(
        "SELECT 1 FROM sessions WHERE token_hash = ? AND expires_at > datetime('now','localtime')",
        (_token_hash(token),),
    ).fetchone()
    return row is not None


def revoke_session(con, token: str) -> None:
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def revoke_all_sessions(con) -> None:
    """Se llama al cambiar el PIN: cualquier sesión abierta en otro dispositivo se cae."""
    con.execute("DELETE FROM sessions")


# --- límite de intentos de login ----------------------------------------------
def login_locked_for(con, ip: str) -> int:
    """Segundos que faltan para que la IP pueda volver a probar (0 si puede)."""
    since = (datetime.now() - timedelta(minutes=LOGIN_WINDOW_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    row = con.execute(
        "SELECT COUNT(*) n, MAX(created_at) last FROM login_attempts WHERE ip = ? AND ok = 0 AND created_at >= ?",
        (ip, since),
    ).fetchone()
    if not row or row["n"] < LOGIN_MAX_FAILS:
        return 0
    last = datetime.strptime(row["last"], "%Y-%m-%d %H:%M:%S")
    left = (last + timedelta(minutes=LOGIN_LOCK_MIN) - datetime.now()).total_seconds()
    return max(0, int(left))


def record_login(con, ip: str, ok: bool) -> None:
    con.execute("INSERT INTO login_attempts(ip, ok) VALUES (?, ?)", (ip, 1 if ok else 0))
    if ok:
        con.execute("DELETE FROM login_attempts WHERE ip = ? AND ok = 0", (ip,))
    con.execute("DELETE FROM login_attempts WHERE created_at < datetime('now','localtime','-1 day')")


# --- cuota para endpoints públicos --------------------------------------------
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request, bucket: str, limit: int, seconds: int) -> None:
    """Ventana deslizante en memoria. Alcanza para un uvicorn de un proceso, que es
    como corre esto; si algún día hay varios workers, hay que mover esto a la base."""
    key = f"{bucket}:{client_ip(request)}"
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > seconds:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Demasiadas solicitudes seguidas. Esperá un momento.")
    q.append(now)
    if len(_hits) > 5000:  # no dejamos crecer el diccionario para siempre
        for k in [k for k, v in list(_hits.items()) if not v or now - v[-1] > 3600]:
            _hits.pop(k, None)


def client_ip(request: Request) -> str:
    """Detrás del proxy la IP real viene en X-Forwarded-For. Se confía en esa cabecera
    solo si TRUST_PROXY está activo, para que nadie la falsifique corriendo sin proxy."""
    if os.environ.get("LOPIANA_TRUST_PROXY", "1") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:45]
    return (request.client.host if request.client else "?")[:45]
