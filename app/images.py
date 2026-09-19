"""Normalización de fotos: toda imagen subida termina con la misma medida.

- Acepta JPG, PNG, WEBP, HEIC/HEIF (fotos de iPhone), GIF, BMP, TIFF.
- Corrige la orientación EXIF (fotos giradas del celular).
- Dos modos:
    cover   -> rellena el marco y recorta al centro (sin bordes, para grilla pareja)
    contain -> encaja completa y rellena con fondo claro (no pierde nada de la prenda)
- Genera la imagen principal (por defecto 1200x1600, 3:4) y una miniatura (600x800).
- Guarda el original tal cual llegó, para poder re-procesar más adelante.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

try:  # HEIC de iPhone
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff"}
PAD_COLOR = (247, 243, 240)  # crema muy claro, combina con el fondo del sitio
CHART_MAX = 1600             # lado largo de la tabla de talles
MAX_PIXELS = 60_000_000      # una foto de 60 MP ya es absurda: corta las bombas de descompresión

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _open(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.verify()                       # descarta archivos que solo dicen ser imágenes
    im = Image.open(io.BytesIO(data))  # verify() deja el archivo consumido: se reabre
    if im.width * im.height > MAX_PIXELS:
        raise ValueError("La imagen es demasiado grande. Mandala en menos resolución.")
    im = ImageOps.exif_transpose(im)  # respeta la orientación de la cámara
    if im.mode in ("RGBA", "LA", "P"):
        # fondo claro debajo de transparencias
        base = Image.new("RGB", im.size, PAD_COLOR)
        im = im.convert("RGBA")
        base.paste(im, mask=im.split()[-1])
        return base
    return im.convert("RGB")


def normalize(im: Image.Image, width: int, height: int, mode: str = "cover") -> Image.Image:
    if mode == "contain":
        fitted = ImageOps.contain(im, (width, height), Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), PAD_COLOR)
        canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
        return canvas
    # cover: llena el marco y recorta centrado
    return ImageOps.fit(im, (width, height), Image.LANCZOS, centering=(0.5, 0.45))


def process_upload(
    data: bytes,
    original_name: str,
    product_dir: Path,
    originals_dir: Path,
    width: int = 1200,
    height: int = 1600,
    mode: str = "cover",
) -> dict:
    """Guarda original + normalizada + thumb. Devuelve nombres de archivo relativos."""
    ext = Path(original_name).suffix.lower() or ".jpg"
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Formato no soportado: {ext}")
    product_dir.mkdir(parents=True, exist_ok=True)
    originals_dir.mkdir(parents=True, exist_ok=True)

    uid = uuid.uuid4().hex[:12]
    original_path = originals_dir / f"{uid}{ext}"
    original_path.write_bytes(data)

    im = _open(data)
    main = normalize(im, width, height, mode)
    thumb = main.resize((width // 2, height // 2), Image.LANCZOS)

    main_name = f"{uid}.jpg"
    thumb_name = f"{uid}_thumb.jpg"
    main.save(product_dir / main_name, "JPEG", quality=88, optimize=True, progressive=True)
    thumb.save(product_dir / thumb_name, "JPEG", quality=84, optimize=True, progressive=True)
    return {
        "filename": main_name,
        "thumb": thumb_name,
        "original": original_path.name,
        "width": width,
        "height": height,
        "source_size": im.size,
    }


def reprocess(original_path: Path, product_dir: Path, width: int, height: int, mode: str, main_name: str, thumb_name: str) -> None:
    """Vuelve a generar main+thumb desde el original (cambio de modo o medida)."""
    im = _open(original_path.read_bytes())
    main = normalize(im, width, height, mode)
    main.save(product_dir / main_name, "JPEG", quality=88, optimize=True, progressive=True)
    main.resize((width // 2, height // 2), Image.LANCZOS).save(product_dir / thumb_name, "JPEG", quality=84, optimize=True, progressive=True)


def process_size_chart(data: bytes, original_name: str, product_dir: Path, originals_dir: Path) -> dict:
    """La tabla de talles no se recorta: es texto y números, tiene que leerse entera.
    Se respeta su proporción y solo se limita el lado largo."""
    ext = Path(original_name).suffix.lower() or ".jpg"
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Formato no soportado: {ext}")
    product_dir.mkdir(parents=True, exist_ok=True)
    originals_dir.mkdir(parents=True, exist_ok=True)

    uid = uuid.uuid4().hex[:12]
    (originals_dir / f"{uid}{ext}").write_bytes(data)

    im = _open(data)
    im = ImageOps.contain(im, (CHART_MAX, CHART_MAX), Image.LANCZOS)
    name = f"{uid}_talles.jpg"
    thumb_name = f"{uid}_talles_thumb.jpg"
    im.save(product_dir / name, "JPEG", quality=90, optimize=True, progressive=True)
    ImageOps.contain(im, (520, 520), Image.LANCZOS).save(product_dir / thumb_name, "JPEG", quality=84, optimize=True)
    return {
        "filename": name,
        "thumb": thumb_name,
        "original": f"{uid}{ext}",
        "width": im.width,
        "height": im.height,
        "source_size": im.size,
    }
