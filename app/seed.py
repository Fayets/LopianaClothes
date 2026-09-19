"""Carga inicial desde seed_img/catalog.json (datos de lopianaclothes.com + fotos de @lopiana.clothes).
Solo crea los productos cuyo slug no exista todavía: se puede correr las veces que haga falta."""
import json

from . import images as imgproc
from .db import BASE_DIR, get_db, init_db, seed_categories

SEED_IMG = BASE_DIR / "seed_img"


def run() -> None:
    init_db()
    catalog = json.loads((SEED_IMG / "catalog.json").read_text())
    with get_db() as con:
        order = (con.execute("SELECT COALESCE(MAX(sort_order),0) FROM products").fetchone()[0] or 0)
        for p in catalog:
            if con.execute("SELECT 1 FROM products WHERE slug = ?", (p["slug"],)).fetchone():
                continue
            order += 1
            cur = con.execute(
                "INSERT INTO products(slug, name, description, category, price, transfer_price, active, sort_order) VALUES (?,?,?,?,?,?,1,?)",
                (p["slug"], p["name"], p["description"], p["category"], p["price"], p.get("transfer_price"), order),
            )
            pid = cur.lastrowid
            for pos, (size, stock) in enumerate(p["sizes"]):
                con.execute("INSERT INTO product_sizes(product_id, size, stock, position) VALUES (?,?,?,?)", (pid, size, stock, pos))
                if stock:
                    con.execute("INSERT INTO stock_moves(product_id, size, delta, reason) VALUES (?,?,?,?)", (pid, size, stock, "alta"))
            for pos, fname in enumerate(p["images"]):
                path = SEED_IMG / fname
                if not path.exists():
                    print("  falta foto:", fname)
                    continue
                info = imgproc.process_upload(path.read_bytes(), path.name, BASE_DIR / "media" / "products" / str(pid), BASE_DIR / "media" / "originals", 1200, 1600, "cover")
                con.execute(
                    "INSERT INTO product_images(product_id, filename, thumb, original, width, height, position) VALUES (?,?,?,?,?,?,?)",
                    (pid, info["filename"], info["thumb"], info["original"], info["width"], info["height"], pos),
                )
            print(f"cargado: {p['name']} ({p['category']})")
        # init_db corrió con la base vacía, así que la lista de categorías se arma acá,
        # una vez que ya existen las prendas de donde salen.
        seed_categories(con)
    print("seed listo")


if __name__ == "__main__":
    run()
