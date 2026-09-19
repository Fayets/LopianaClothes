/* Lopiana Clothes · tienda (estructura El Camarín) + carrito a WhatsApp */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const money = (v) => "$ " + Math.round(v).toLocaleString("es-AR");
  const cap = (s) => (s || "").toLowerCase().replace(/(^|\s|&\s)(\S)/g, (m) => m.toUpperCase());
  const store = { get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
  const sessionId = store.get("lp_session", null) || (() => { const id = Math.random().toString(36).slice(2) + Date.now().toString(36); store.set("lp_session", id); return id; })();
  const track = (type, extra = {}) => fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type, session_id: sessionId, ...extra }), keepalive: true }).catch(() => {});

  let settings = {}, products = [], current = null, size = null, color = null, qty = 1;
  let category = "", sizeFilter = new Set(), priceFilter = new Set(), sort = "featured", query = "";
  let cart = store.get("lp_cart", []);
  const waUrl = (text) => `https://wa.me/${settings.whatsapp_number}?text=${encodeURIComponent(text)}`;
  const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2200); };
  const categories = () => [...new Set(products.map(p => p.category).filter(Boolean))];

  // ---------------- menú, barra lateral, footer
  function renderNav() {
    const cats = categories();
    const nav = $("#nav"); $$("a[data-cat]", nav).forEach(a => a.dataset.cat !== "" && a.remove());
    const anchor = nav.querySelector(".nav-sec");
    cats.forEach(c => { const a = document.createElement("a"); a.href = "/#tienda"; a.dataset.cat = c; a.dataset.home = ""; a.textContent = c; nav.insertBefore(a, anchor); });
    $("#mnavLinks").innerHTML = `<a href="/" data-home data-cat="">Inicio</a>` + cats.map(c => `<a href="/#tienda" data-home data-cat="${c}">${c}</a>`).join("") + `<a href="/#nosotras" class="sec" data-home>Nosotras</a><a href="/#como-comprar" class="sec" data-home>Cómo comprar</a><a href="/#contacto" class="sec" data-home>Contacto</a>`;
    $("#footerCats").innerHTML = `<li><a href="/#tienda" data-home data-cat="">Todas las prendas</a></li>` + cats.map(c => `<li><a href="/#tienda" data-home data-cat="${c}">${c}</a></li>`).join("");
    $("#sideCats").innerHTML = `<li><a href="/#tienda" data-home data-cat="">Todas</a></li>` + cats.map(c => `<li><a href="/#tienda" data-home data-cat="${c}">${c}</a></li>`).join("");
    const sizes = [...new Set(products.flatMap(p => p.sizes.map(s => s.size)))];
    $("#sideSizes").innerHTML = sizes.map(s => `<li><label><input type="checkbox" value="${s}"> ${s}</label></li>`).join("") || `<li class="muted">—</li>`;
    $$("#sideSizes input").forEach(i => i.onchange = () => { i.checked ? sizeFilter.add(i.value) : sizeFilter.delete(i.value); renderGrid(); updateFilterCount(); });
    bindLinks(); markCategory();
  }
  function markCategory() {
    $$("[data-cat]").forEach(a => { if (a.closest("#nav") || a.closest("#sideCats")) a.classList.toggle("on", a.dataset.cat === category); });
    $("#shopTitle").textContent = category ? category : "Novedades";
    $("#crumbCurrent").textContent = category ? cap(category) : "Novedades";
    document.title = (category ? cap(category) + " · " : "") + "Lopiana Clothes";
  }
  function setCategory(c) { category = c || ""; markCategory(); renderGrid(); }

  // ---------------- grilla
  function card(p) {
    const sold = p.sizes.length && p.total_stock === 0, last = p.sizes.length && p.total_stock === 1;
    const c = document.createElement("a"); c.className = "card"; c.href = "/p/" + p.slug;
    const alt = p.images[1] ? `<img class="alt" src="${p.images[1].thumb_url}" alt="" loading="lazy">` : "";
    c.innerHTML = `<div class="card-img"><img src="${p.images[0] ? p.images[0].thumb_url : ""}" alt="${p.name}" loading="lazy">${alt}
        ${sold ? '<span class="card-tag sold">Sin stock</span>' : last ? '<span class="card-tag">Última pieza</span>' : ""}</div>
      <div class="card-body"><h4>${p.name}</h4><div class="card-price"><span>${money(p.transfer_price_final)}</span><s>${money(p.price)}</s></div></div>`;
    c.addEventListener("click", (e) => { e.preventDefault(); openProduct(p); });
    return c;
  }
  function inPrice(p) { if (!priceFilter.size) return true; return [...priceFilter].some(r => { const [a, b] = r.split("-").map(Number); return p.transfer_price_final >= a && p.transfer_price_final <= b; }); }
  function updateFilterCount() {
    const n = sizeFilter.size + priceFilter.size, el = $("#filtersCount");
    el.textContent = n; el.hidden = n === 0;
  }
  function renderGrid() {
    let list = products.filter(p => (!category || p.category === category) && inPrice(p)
      && (!sizeFilter.size || p.sizes.some(s => sizeFilter.has(s.size) && s.stock > 0))
      && (!query || (p.name + " " + p.category + " " + p.description).toLowerCase().includes(query)));
    const sorters = { "price-asc": (a, b) => a.transfer_price_final - b.transfer_price_final, "price-desc": (a, b) => b.transfer_price_final - a.transfer_price_final, az: (a, b) => a.name.localeCompare(b.name), za: (a, b) => b.name.localeCompare(a.name) };
    if (sorters[sort]) list = [...list].sort(sorters[sort]);
    const g = $("#grid"); g.innerHTML = ""; $("#gridEmpty").hidden = list.length > 0;
    list.forEach(p => g.appendChild(card(p)));
  }

  // ---------------- vistas
  function showHome(scrollTo) {
    $("#pdp").hidden = true; $("#home").hidden = false; document.body.classList.remove("on-pdp"); markCategory();
    if (scrollTo) { const el = document.querySelector(scrollTo); if (el) el.scrollIntoView({ behavior: "instant", block: "start" }); }
  }
  function openProduct(p, push = true) {
    current = p; size = null; qty = 1;
    color = p.colors.length ? p.colors[0].name : null;
    if (push) history.pushState({ slug: p.slug }, "", "/p/" + p.slug);
    const img = p.images[0];
    $("#galleryMain").src = img ? img.url : ""; $("#galleryMain").alt = p.name;
    const thumbs = $("#galleryThumbs"); thumbs.innerHTML = "";
    p.images.forEach((im, i) => { const b = document.createElement("button"); b.type = "button"; b.className = i === 0 ? "on" : ""; b.innerHTML = `<img src="${im.thumb_url}" alt="">`; b.onclick = () => { $("#galleryMain").src = im.url; $$("button", thumbs).forEach(x => x.classList.remove("on")); b.classList.add("on"); }; thumbs.appendChild(b); });
    thumbs.hidden = p.images.length < 2; $(".gallery").classList.toggle("single", p.images.length < 2);
    $("#crumbCat").textContent = cap(p.category || "Tienda"); $("#crumbCat").dataset.cat = p.category || "";
    $("#crumbName").textContent = p.name; $("#pName").textContent = p.name;
    $("#pTransfer").textContent = money(p.transfer_price_final); $("#pList").textContent = money(p.price); $("#pPctNote").textContent = p.discount_pct;
    $("#pDesc").textContent = p.description || ""; $("#qtyVal").textContent = qty;
    $("#askBtn").href = waUrl(`Hola Lopiana! Quiero consultar por ${p.name} (${money(p.transfer_price_final)} con transferencia).`);
    const chart = $("#chartLink"); chart.hidden = !p.size_chart;
    if (p.size_chart) { $("#chartImg").src = p.size_chart.url; $("#chartNote").textContent = settings.size_chart_note || ""; }
    renderColors(); renderSizes(); renderRelated(p);
    document.title = `${p.name} · Lopiana Clothes`;
    $("#home").hidden = true; $("#pdp").hidden = false; document.body.classList.add("on-pdp");
    window.scrollTo({ top: 0, behavior: "instant" });
    track("view_product", { product_id: p.id });
  }
  function renderRelated(p) {
    const others = products.filter(x => x.id !== p.id).sort((a, b) => (b.category === p.category) - (a.category === p.category)).slice(0, 4);
    $("#related").hidden = others.length === 0; const g = $("#relatedGrid"); g.innerHTML = ""; others.forEach(o => g.appendChild(card(o)));
  }
  function route() {
    const m = location.pathname.match(/^\/p\/([^/]+)\/?$/);
    if (m) { const p = products.find(x => x.slug === decodeURIComponent(m[1])); if (p) { openProduct(p, false); return; } history.replaceState(null, "", "/"); }
    showHome(location.hash || null);
  }
  function goHome(hash, cat) {
    if (cat !== undefined) setCategory(cat);
    if (!$("#pdp").hidden) { history.pushState(null, "", "/" + (hash || "")); showHome(hash || null); }
    else if (hash) document.querySelector(hash)?.scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function bindLinks() {
    $$("a[data-home]").forEach(a => {
      if (a.dataset.bound) return; a.dataset.bound = 1;
      a.addEventListener("click", (e) => { e.preventDefault(); closeMnav(); $("#side").classList.remove("open"); $("#sideBackdrop").hidden = true; document.body.style.overflow = ""; const href = a.getAttribute("href") || "/"; const hash = href.includes("#") ? "#" + href.split("#")[1] : ""; goHome(hash, a.dataset.cat); });
    });
  }

  function renderColors() {
    const p = current, wrap = $("#colors"), field = $("#colorField");
    wrap.innerHTML = ""; field.hidden = !p.colors.length;
    if (!p.colors.length) { color = null; return; }
    p.colors.forEach(c => {
      const b = document.createElement("button"); b.type = "button"; b.className = "swatch" + (color === c.name ? " on" : "");
      b.style.setProperty("--tone", c.hex); b.title = c.name; b.setAttribute("aria-label", c.name);
      b.onclick = () => { color = c.name; renderColors(); };
      wrap.appendChild(b);
    });
    $("#colorName").textContent = color || "";
  }

  function renderSizes() {
    const p = current, wrap = $("#sizes"), field = $("#sizeField"), hint = $("#stockHint");
    wrap.innerHTML = "";
    if (!p.sizes.length) { field.hidden = true; $("#addBtn").disabled = false; $("#addBtn").textContent = "Agregar al carrito"; return; }
    field.hidden = false; let any = false;
    p.sizes.forEach(s => { const b = document.createElement("button"); b.type = "button"; b.textContent = s.size; if (s.stock <= 0) b.disabled = true; else any = true; if (s.stock === 1) b.classList.add("last"); if (size === s.size) b.classList.add("on"); b.onclick = () => { size = s.size; qty = 1; $("#qtyVal").textContent = qty; renderSizes(); }; wrap.appendChild(b); });
    const sel = p.sizes.find(s => s.size === size);
    hint.textContent = !any ? "Sin stock" : sel ? (sel.stock === 1 ? "Queda la última" : `${sel.stock} disponibles`) : "Elegí tu talle";
    $("#addBtn").disabled = !any; $("#addBtn").textContent = any ? "Agregar al carrito" : "Sin stock";
    syncBuyBar();
  }

  function syncBuyBar() {
    const p = current; if (!p) return;
    const any = !p.sizes.length || p.sizes.some(s => s.stock > 0);
    $("#barPrice").textContent = money(p.transfer_price_final);
    $("#barNote").textContent = !any ? "Sin stock" : p.sizes.length && !size ? "Elegí tu talle" : size ? "Talle " + size : "Disponible";
    $("#barAdd").disabled = !any; $("#barAdd").textContent = any ? "Agregar" : "Sin stock";
  }

  // ---------------- carrito
  const cartCount = () => cart.reduce((n, i) => n + i.qty, 0);
  function saveCart() { store.set("lp_cart", cart); const c = $("#cartCount"); c.textContent = cartCount(); c.classList.toggle("zero", cartCount() === 0); }
  function stockFor(pid, sz) { const p = products.find(x => x.id === pid); if (!p) return 0; if (!p.sizes.length) return 99; const s = p.sizes.find(x => x.size === sz); return s ? s.stock : 0; }
  function addToCart() {
    if (!current) return;
    if (current.sizes.length && !size) { toast("Elegí un talle primero"); return; }
    if (current.colors.length && !color) { toast("Elegí un color primero"); return; }
    const key = `${current.id}:${size || ""}:${color || ""}`, ex = cart.find(i => i.key === key), max = stockFor(current.id, size), want = (ex ? ex.qty : 0) + qty;
    if (want > max) { toast(max === 0 ? "No hay stock de ese talle" : `Solo quedan ${max} de ese talle`); return; }
    if (ex) ex.qty = want; else cart.push({ key, product_id: current.id, name: current.name, size, color, qty, unit: current.transfer_price_final, list: current.price, img: current.images[0] ? current.images[0].thumb_url : "" });
    saveCart(); track("add_to_cart", { product_id: current.id, size, meta: { qty, color } });
    const m = $("#addedMsg"); m.hidden = false; setTimeout(() => (m.hidden = true), 2500);
    openDrawer();
  }
  function renderCart() {
    const list = $("#cartItems"); list.innerHTML = "";
    const empty = cart.length === 0;
    $("#cartEmpty").hidden = !empty; $("#checkoutForm").hidden = empty; $("#checkoutDone").hidden = true;
    const pay = document.querySelector('input[name="pay"]:checked')?.value || "transferencia", disc = pay !== "otro";
    let list_total = 0, total = 0;
    cart.forEach(i => {
      const unit = disc ? i.unit : i.list; list_total += i.list * i.qty; total += unit * i.qty;
      const el = document.createElement("div"); el.className = "ci";
      el.innerHTML = `<img src="${i.img}" alt=""><div><h5>${i.name}</h5><p>${i.size ? "Talle " + i.size + " · " : ""}${i.color ? i.color + " · " : ""}<span class="ci-price">${money(unit * i.qty)}</span></p></div>
        <div class="ci-ctrl"><div class="qty"><button type="button" data-d="-1">−</button><span>${i.qty}</span><button type="button" data-d="1">+</button></div><button type="button" class="rm">quitar</button></div>`;
      $$("[data-d]", el).forEach(b => b.onclick = () => { const d = +b.dataset.d, max = stockFor(i.product_id, i.size); if (i.qty + d > max) { toast(`Solo quedan ${max}`); return; } i.qty += d; if (i.qty <= 0) cart = cart.filter(x => x !== i); saveCart(); renderCart(); });
      el.querySelector(".rm").onclick = () => { cart = cart.filter(x => x !== i); saveCart(); renderCart(); track("remove_from_cart", { product_id: i.product_id, size: i.size }); };
      list.appendChild(el);
    });
    $("#sumList").textContent = money(list_total); $("#sumTotal").textContent = money(total);
    $("#sumLabel").textContent = pay === "transferencia" ? "con transferencia" : pay === "efectivo" ? "en efectivo" : "precio de lista";
    $("#sumList").parentElement.hidden = !disc;
  }
  function openDrawer() { renderCart(); $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); $("#drawerBackdrop").hidden = false; document.body.style.overflow = "hidden"; }
  function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#drawerBackdrop").hidden = true; document.body.style.overflow = ""; }
  function openMnav() { $("#mnav").classList.add("open"); $("#mnavBackdrop").hidden = false; }
  function closeMnav() { $("#mnav").classList.remove("open"); $("#mnavBackdrop").hidden = true; }

  async function checkout(e) {
    e.preventDefault();
    const btn = $("#checkoutBtn"), err = $("#checkoutErr"); err.hidden = true;
    const name = $("#cName").value.trim();
    if (!name) { err.textContent = "Contanos tu nombre para identificar el pedido."; err.hidden = false; $("#cName").focus(); return; }
    btn.disabled = true; btn.textContent = "Reservando...";
    const win = window.open("", "_blank");
    try {
      const r = await fetch("/api/orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: cart.map(i => ({ product_id: i.product_id, size: i.size, color: i.color, qty: i.qty })), customer_name: name, customer_phone: $("#cPhone").value.trim(), payment: document.querySelector('input[name="pay"]:checked').value, session_id: sessionId }) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "No se pudo crear el pedido");
      if (win) win.location.href = data.whatsapp_url; else window.open(data.whatsapp_url, "_blank");
      cart = []; saveCart();
      $("#checkoutForm").hidden = true; $("#cartItems").innerHTML = ""; $("#cartEmpty").hidden = true;
      $("#doneCode").textContent = data.order.code; $("#doneWa").href = data.whatsapp_url; $("#checkoutDone").hidden = false;
      await loadProducts();
    } catch (ex) { if (win) win.close(); err.textContent = ex.message; err.hidden = false; await loadProducts(); }
    finally { btn.disabled = false; btn.textContent = "Finalizar por WhatsApp"; }
  }

  // ---------------- carga
  async function loadProducts() {
    products = await (await fetch("/api/products")).json();
    renderNav(); renderGrid();
    if (current) { const p = products.find(x => x.id === current.id); if (p) { current = p; if (!$("#pdp").hidden) { const s = size; renderSizes(); size = s; renderSizes(); } } }
  }
  async function init() {
    settings = await (await fetch("/api/settings/public")).json();
    $("#bannerText").textContent = settings.banner_text || "";
    $("#fAddress").textContent = settings.address || ""; $("#accAddress").textContent = settings.address || "";
    $("#year").textContent = new Date().getFullYear();
    const pct = settings.transfer_discount_pct || "30";
    $("#payPct1").textContent = `-${pct}%`; $("#payPct2").textContent = `-${pct}%`; $("#accPct").textContent = pct;
    const generic = waUrl("Hola Lopiana! Quiero hacer una consulta.");
    ["#headerWa", "#fWa", "#fWa2", "#waFloat", "#mnavWa"].forEach(s => $(s).href = generic);
    $("#fWaText").textContent = "+" + (settings.whatsapp_number || "").replace(/^(\d{2})(\d)(\d{2})(\d{4})(\d{4})$/, "$1 $2 $3 $4-$5");
    $("#fMail").href = "mailto:" + (settings.email || ""); $("#fMailText").textContent = settings.email || "";
    if (settings.instagram) { const ig = "https://www.instagram.com/" + settings.instagram + "/"; ["#igLink", "#fIg", "#mnavIg"].forEach(s => $(s).href = ig); }
    $("#waFloat").addEventListener("click", () => track("whatsapp_float"));
    $("#headerWa").addEventListener("click", () => track("whatsapp_header"));
    $("#askBtn").addEventListener("click", () => track("whatsapp_product", { product_id: current && current.id }));
    $("#copyLink").onclick = async () => { try { await navigator.clipboard.writeText(location.href); toast("Link copiado"); } catch { toast(location.href); } };
    $("#qtyMinus").onclick = () => { qty = Math.max(1, qty - 1); $("#qtyVal").textContent = qty; };
    $("#qtyPlus").onclick = () => { const max = current && current.sizes.length ? (size ? stockFor(current.id, size) : 1) : 20; qty = Math.min(Math.max(1, max), qty + 1); $("#qtyVal").textContent = qty; };
    $("#addBtn").onclick = addToCart;
    $("#barAdd").onclick = () => { if (current && current.sizes.length && !size) { $("#sizeField").scrollIntoView({ behavior: "smooth", block: "center" }); toast("Elegí tu talle"); return; } addToCart(); };

    const openSheet = () => { $("#chartSheet").classList.add("open"); $("#chartSheet").setAttribute("aria-hidden", "false"); $("#chartBackdrop").hidden = false; document.body.style.overflow = "hidden"; };
    const closeSheet = () => { $("#chartSheet").classList.remove("open"); $("#chartSheet").setAttribute("aria-hidden", "true"); $("#chartBackdrop").hidden = true; document.body.style.overflow = ""; };
    $("#chartLink").onclick = openSheet; $("#chartClose").onclick = closeSheet; $("#chartBackdrop").onclick = closeSheet;

    const openFilters = () => { $("#side").classList.add("open"); $("#sideBackdrop").hidden = false; document.body.style.overflow = "hidden"; };
    const closeFilters = () => { $("#side").classList.remove("open"); $("#sideBackdrop").hidden = true; document.body.style.overflow = ""; };
    $("#filtersBtn").onclick = openFilters; $("#sideClose").onclick = closeFilters; $("#sideBackdrop").onclick = closeFilters; $("#sideApply").onclick = closeFilters;
    $("#sideClear").onclick = () => { sizeFilter.clear(); priceFilter.clear(); $$("#sideSizes input, #sidePrices input").forEach(i => i.checked = false); renderGrid(); updateFilterCount(); };
    $("#cartBtn").onclick = () => { openDrawer(); track("open_cart"); };
    $("#drawerClose").onclick = closeDrawer; $("#drawerBackdrop").onclick = closeDrawer; $("#doneClose").onclick = closeDrawer;
    $("#emptyGo").addEventListener("click", closeDrawer);
    $("#burger").onclick = openMnav; $("#mnavClose").onclick = closeMnav; $("#mnavBackdrop").onclick = closeMnav;
    $("#searchBtn").onclick = () => { const f = $("#searchForm"); f.hidden = !f.hidden; if (!f.hidden) $("#searchInput").focus(); else { query = ""; $("#searchInput").value = ""; renderGrid(); } };
    $("#searchInput").oninput = (e) => { query = e.target.value.trim().toLowerCase(); renderGrid(); if (!$("#pdp").hidden) goHome("#tienda"); };
    $("#searchForm").onsubmit = (e) => { e.preventDefault(); goHome("#tienda"); };
    $("#sortSel").onchange = (e) => { sort = e.target.value; renderGrid(); };
    $$("#sidePrices input").forEach(i => i.onchange = () => { i.checked ? priceFilter.add(i.value) : priceFilter.delete(i.value); renderGrid(); updateFilterCount(); });
    $("#newsForm").onsubmit = async (e) => { e.preventDefault(); const email = $("#newsEmail").value.trim(); if (!email) return; const r = await fetch("/api/newsletter", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, session_id: sessionId }) }); if (r.ok) { $("#newsForm").hidden = true; $("#newsOk").hidden = false; } else toast("No pudimos guardar tu email"); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); closeMnav(); closeSheet(); closeFilters(); } });
    $$('input[name="pay"]').forEach(r => r.onchange = renderCart);
    $("#checkoutForm").onsubmit = checkout;
    saveCart();
    await loadProducts();
    bindLinks(); route();
    window.addEventListener("popstate", route);
  }
  init();
})();
