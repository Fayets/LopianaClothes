/* Lopiana · panel de gestión */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const money = (v) => "$ " + Math.round(v).toLocaleString("es-AR");
  const fmtDate = (s) => { const d = new Date(s.replace(" ", "T")); return d.toLocaleDateString("es-AR", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" }); };
  const toast = (m) => { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2200); };
  async function api(url, opts = {}) {
    const r = await fetch(url, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
    if (r.status === 401) { showLogin(); throw new Error("Sesión vencida"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || "Error");
    return data;
  }

  let days = 30, month = null, statusFilter = "", products = [], editing = null, settingsCache = {}, cats = [];
  // Las fotos se guardan bajo el id del producto, que en una prenda nueva todavía no
  // existe. En vez de obligar a guardar primero, quedan acá en espera con una vista
  // previa local y se suben solas apenas la prenda se crea.
  let pendientes = { fotos: [], tabla: null };
  const soltarPendientes = () => {
    pendientes.fotos.forEach(f => URL.revokeObjectURL(f.preview));
    if (pendientes.tabla) URL.revokeObjectURL(pendientes.tabla.preview);
    pendientes = { fotos: [], tabla: null };
  };
  const MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

  // ---------------- login
  function showLogin() { $("#login").hidden = false; $("#pinGate").hidden = true; $("#app").hidden = true; }
  function showGate() { $("#login").hidden = true; $("#pinGate").hidden = false; $("#app").hidden = true; }
  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault(); $("#loginErr").hidden = true;
    try {
      const r = await api("/api/admin/login", { method: "POST", body: JSON.stringify({ pin: $("#pin").value }) });
      $("#pin").value = "";
      r.must_change_pin ? showGate() : start();
    } catch (ex) { $("#loginErr").textContent = ex.message; $("#loginErr").hidden = false; }
  };
  $("#pinGateForm").onsubmit = async (e) => {
    e.preventDefault(); const err = $("#gateErr"); err.hidden = true;
    const a = $("#gateNew").value, b = $("#gateRepeat").value;
    if (a !== b) { err.textContent = "Los dos PIN no coinciden."; err.hidden = false; return; }
    try { await api("/api/admin/pin", { method: "POST", body: JSON.stringify({ new_pin: a }) }); $("#gateNew").value = $("#gateRepeat").value = ""; toast("PIN actualizado"); start(); }
    catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
  $("#logout").onclick = async () => { await api("/api/admin/logout", { method: "POST" }); showLogin(); };

  // ---------------- tabs
  $$(".side nav button, .tabbar button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
  function showTab(name) {
    $$(".side nav button, .tabbar button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
    $$("[data-panel]").forEach(p => p.hidden = p.dataset.panel !== name);
    window.scrollTo({ top: 0 });
    ({ resumen: loadStats, productos: loadProducts, pedidos: loadOrders, ajustes: loadSettings })[name]();
  }

  // ---------------- resumen
  $$("#daysSeg button").forEach(b => b.onclick = () => {
    $$("#daysSeg button").forEach(x => x.classList.toggle("on", x === b));
    if (b.dataset.d === "month") { month = $("#monthSel").value || new Date().toISOString().slice(0, 7); $("#monthSel").hidden = false; }
    else { month = null; days = +b.dataset.d; $("#monthSel").hidden = true; }
    loadStats();
  });
  $("#monthSel").onchange = () => { month = $("#monthSel").value; loadStats(); };
  function fillMonths(first) {
    const sel = $("#monthSel"); if (sel.options.length) return;
    const now = new Date(); let y = now.getFullYear(), m = now.getMonth() + 1;
    const [fy, fm] = first.split("-").map(Number);
    for (let i = 0; i < 24; i++) {
      const val = `${y}-${String(m).padStart(2, "0")}`;
      sel.insertAdjacentHTML("beforeend", `<option value="${val}">${MESES[m - 1]} ${y}</option>`);
      if (y === fy && m === fm) break;
      m--; if (m === 0) { m = 12; y--; }
    }
  }
  async function loadStats() {
    const s = await api(month ? `/api/admin/stats?month=${month}` : `/api/admin/stats?days=${days}`);
    fillMonths(s.first_month);
    const ob = s.orders_by_status, pend = ob.pendiente || 0;
    $("#pendingPill").textContent = pend; $("#pendingPill").hidden = !pend; $("#pendingDot").hidden = !pend;
    $("#kpis").innerHTML = [
      ["Visitas", s.visitas, ""], ["Vistas de prenda", s.vistas_producto, ""],
      ["Agregados al carrito", s.lo_quiero, "hi"], ["Pedidos a WhatsApp", s.whatsapp, "hi"],
      ["Conversión", s.conversion_lo_quiero_a_whatsapp + "%", "", "Carrito → WhatsApp"],
      ["Pendientes", pend, "", money(s.pending_total)],
      ["Ventas confirmadas", money(s.revenue), "", `${(ob.confirmado || 0) + (ob.entregado || 0)} pedidos`],
      ["Suscriptores newsletter", s.suscriptores, ""],
    ].map(([l, v, c, e]) => `<div class="kpi ${c}"><small>${l}</small><b>${v}</b>${e ? `<em>${e}</em>` : ""}</div>`).join("");
    // chart (fechas en hora local, igual que la base)
    const ch = $("#chart"), ax = $("#chartAxis"); ch.innerHTML = ""; ax.innerHTML = "";
    const fmtDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const daysList = [];
    if (month) {
      const [y, m] = month.split("-").map(Number); const today = new Date(); today.setHours(0, 0, 0, 0);
      for (let d = new Date(y, m - 1, 1); d.getMonth() === m - 1 && d <= today; d.setDate(d.getDate() + 1)) daysList.push(fmtDay(d));
      if (!daysList.length) daysList.push(`${month}-01`);
    } else { for (let i = days - 1; i >= 0; i--) { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i); daysList.push(fmtDay(d)); } }
    const n = daysList.length;
    const map = Object.fromEntries(s.daily.map(d => [d.day, d]));
    const max = Math.max(1, ...s.daily.map(d => Math.max(d.lo_quiero, d.whatsapp)));
    const step = n <= 7 ? 1 : n <= 31 ? 5 : 15;
    daysList.forEach((day, i) => {
      const d = map[day] || { lo_quiero: 0, whatsapp: 0 };
      const b = document.createElement("div"); b.className = "bar"; b.title = `${day.slice(8)}/${day.slice(5, 7)}: ${d.lo_quiero} Lo quiero · ${d.whatsapp} WhatsApp`;
      b.innerHTML = `<i class="${d.lo_quiero ? "on" : ""}" style="height:${d.lo_quiero / max * 100}%"></i><i class="wa ${d.whatsapp ? "on" : ""}" style="height:${d.whatsapp / max * 100}%"></i>`;
      ch.appendChild(b);
      const l = document.createElement("span"); l.textContent = (i % step === 0 || i === n - 1) ? `${day.slice(8)}/${day.slice(5, 7)}` : ""; ax.appendChild(l);
    });
    $("#perProduct tbody").innerHTML = s.per_product.map(p => `<tr><td>${p.name}</td><td>${p.vistas}</td><td><b>${p.lo_quiero}</b></td><td>${p.vendidos}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Sin prendas todavía</td></tr>`;
    const agotados = s.low_stock.filter(l => l.stock === 0), ultimos = s.low_stock.filter(l => l.stock === 1);
    $("#stockNote").textContent = `${ultimos.length} talle${ultimos.length === 1 ? "" : "s"} con última unidad · ${agotados.length} agotado${agotados.length === 1 ? "" : "s"}`;
    $("#lowStock").innerHTML = agotados.length ? agotados.map(l => `<li><span>${l.name} <em>· talle ${l.size}</em></span><b>Agotado</b></li>`).join("") : `<li><em>Ningún talle agotado.</em></li>`;
  }

  // ---------------- productos
  async function loadProducts() {
    products = await api("/api/admin/products");
    if (!cats.length) cats = await api("/api/admin/categories").catch(() => []);
    const list = $("#plist");
    if (!products.length) { list.innerHTML = `<div class="empty">Todavía no hay prendas. Creá la primera con <b>+ Nueva prenda</b>.</div>`; return; }
    list.innerHTML = products.map(p => `<div class="prow" data-id="${p.id}">
      ${p.images[0] ? `<img src="${p.images[0].thumb_url}" alt="">` : `<div class="noimg"></div>`}
      <div><h4>${p.name}</h4><p>${p.category || "sin categoría"} · ${money(p.transfer_price_final)} transf. · ${p.images.length} foto${p.images.length === 1 ? "" : "s"}${p.colors.length ? ` · ${p.colors.length} color${p.colors.length === 1 ? "" : "es"}` : ""}${p.size_chart ? " · con tabla" : ""}</p></div>
      <span class="st ${p.sizes.length && p.total_stock === 0 ? "zero" : ""}">${p.sizes.length ? `Stock: ${p.total_stock} (${p.sizes.map(s => s.size + " " + s.stock).join(" · ")})` : "Sin control de stock"}</span>
      <span class="badge ${p.active ? "on" : ""}">${p.active ? "Visible" : "Oculta"}</span>
      <span class="link">Editar</span></div>`).join("");
    $$(".prow").forEach(r => r.onclick = () => openEditor(products.find(p => p.id === +r.dataset.id)));
  }
  $("#newProduct").onclick = () => openEditor(null);

  function sizeRow(size = "", stock = 0) {
    const d = document.createElement("div"); d.className = "srow";
    d.innerHTML = `<input placeholder="Talle (S, M, 40, único...)" value="${size}"><input type="number" min="0" placeholder="Stock" value="${stock}"><button type="button" title="Quitar">×</button>`;
    d.querySelector("button").onclick = () => d.remove();
    return d;
  }
  $("#addSize").onclick = () => $("#sizesRows").appendChild(sizeRow());

  function colorRow(name = "", hex = "#1b1b1b") {
    const d = document.createElement("div"); d.className = "srow crow";
    d.innerHTML = `<input placeholder="Nombre del color (Negro, Crema...)" value="${name.replace(/"/g, "&quot;")}" maxlength="40">
      <input type="color" value="${hex}" title="Elegí el tono que se ve en la ficha">
      <button type="button" title="Quitar">×</button>`;
    d.querySelector("button").onclick = () => d.remove();
    return d;
  }
  $("#addColor").onclick = () => $("#colorRows").appendChild(colorRow());

  function openEditor(p) {
    editing = p; const f = $("#editorForm");
    $("#editorTitle").textContent = p ? p.name : "Nueva prenda";
    f.name.value = p ? p.name : "";
    const actual = p ? p.category : "";
    // Si una prenda vieja tiene una categoría que ya no está en la lista, se agrega como
    // opción para no cambiársela en silencio al guardar.
    const opciones = cats.map(c => c.name);
    if (actual && !opciones.includes(actual)) opciones.push(actual);
    f.category.innerHTML = `<option value="">— Sin categoría —</option>` +
      opciones.map(n => `<option value="${n.replace(/"/g, "&quot;")}"${n === actual ? " selected" : ""}>${n}</option>`).join("");
    $("#catHint").hidden = opciones.length > 0 && cats.length > 0; f.price.value = p ? p.price : ""; f.transfer_price.value = p && p.transfer_price ? p.transfer_price : "";
    f.description.value = p ? p.description : ""; f.active.checked = p ? !!p.active : true;
    $("#sizesRows").innerHTML = ""; (p ? p.sizes : [{ size: "S", stock: 1 }, { size: "M", stock: 1 }, { size: "L", stock: 1 }]).forEach(s => $("#sizesRows").appendChild(sizeRow(s.size, s.stock)));
    $("#colorRows").innerHTML = ""; (p ? p.colors : []).forEach(c => $("#colorRows").appendChild(colorRow(c.name, c.hex)));
    soltarPendientes();
    $("#deleteProduct").hidden = !p; $("#editorErr").hidden = true; $("#uploadStatus").hidden = true;
    $("#drop").hidden = false; $("#noImgs").hidden = true; $("#chartEd").hidden = false;
    $$('input[name="imgmode"]').forEach(r => r.checked = r.value === (settingsCache.image_mode || "cover"));
    renderThumbs(); renderChart();
    $("#editor").hidden = false; $("#editorBackdrop").hidden = false;
    document.body.classList.add("modal-open");
  }
  function closeEditor() { soltarPendientes(); $("#editor").hidden = true; $("#editorBackdrop").hidden = true; document.body.classList.remove("modal-open"); editing = null; loadProducts(); }
  $("#editorClose").onclick = closeEditor; $("#editorBackdrop").onclick = closeEditor;

  function collect() {
    const f = $("#editorForm");
    return { name: f.name.value.trim(), category: f.category.value.trim(), price: +f.price.value || 0, transfer_price: f.transfer_price.value ? +f.transfer_price.value : null, description: f.description.value, active: f.active.checked,
      sizes: $$("#sizesRows .srow").map(r => ({ size: r.children[0].value.trim(), stock: +r.children[1].value || 0 })).filter(s => s.size),
      colors: $$("#colorRows .crow").map(r => ({ name: r.children[0].value.trim(), hex: r.children[1].value })).filter(c => c.name) };
  }
  $("#editorForm").onsubmit = async (e) => {
    e.preventDefault(); $("#editorErr").hidden = true;
    try {
      const body = JSON.stringify(collect());
      const btn = $("#saveProduct"); btn.disabled = true;
      const saved = editing ? await api(`/api/admin/products/${editing.id}`, { method: "PUT", body }) : await api("/api/admin/products", { method: "POST", body });
      const isNew = !editing; editing = saved; $("#editorTitle").textContent = saved.name;
      $("#deleteProduct").hidden = false;
      const subidas = await subirPendientes();
      btn.disabled = false;
      toast(isNew ? (subidas ? `Prenda creada con ${subidas} foto${subidas === 1 ? "" : "s"}` : "Prenda creada") : "Guardado");
      closeEditor();
    } catch (ex) { $("#saveProduct").disabled = false; $("#editorErr").textContent = ex.message; $("#editorErr").hidden = false; }
  };

  async function subirPendientes() {
    if (!editing) return 0;
    let n = 0;
    if (pendientes.fotos.length) {
      const st = $("#uploadStatus"); st.hidden = false;
      st.textContent = `Subiendo ${pendientes.fotos.length} foto${pendientes.fotos.length > 1 ? "s" : ""}...`;
      const fd = new FormData();
      pendientes.fotos.forEach(f => fd.append("files", f.file));
      fd.append("mode", pendientes.fotos[0].mode);
      const out = await api(`/api/admin/products/${editing.id}/images`, { method: "POST", body: fd });
      editing.images.push(...out); n += out.length;
    }
    if (pendientes.tabla) {
      $("#uploadStatus").hidden = false; $("#uploadStatus").textContent = "Subiendo la tabla de talles...";
      const fd = new FormData(); fd.append("file", pendientes.tabla.file);
      editing = await api(`/api/admin/products/${editing.id}/size-chart`, { method: "POST", body: fd }); n += 1;
    }
    soltarPendientes();
    return n;
  }

  $("#deleteProduct").onclick = async () => {
    if (!editing || !confirm(`¿Eliminar "${editing.name}" con sus fotos? No se puede deshacer.`)) return;
    await api(`/api/admin/products/${editing.id}`, { method: "DELETE" }); toast("Prenda eliminada"); closeEditor();
  };

  // fotos
  function renderThumbs() {
    const wrap = $("#imgThumbs"); wrap.innerHTML = "";
    editing ? thumbsGuardadas(wrap) : thumbsPendientes(wrap);
  }

  function marco(html, principal) {
    const d = document.createElement("div");
    d.className = "th" + (principal ? " is-main" : "");
    d.innerHTML = html;
    return d;
  }

  function thumbsGuardadas(wrap) {
    editing.images.forEach((im, i) => {
      const d = marco(`<img src="${im.thumb_url}?v=${Date.now()}" alt="">
        ${i === 0 ? '<span class="first">Principal</span>' : '<button type="button" class="mk">Hacer principal</button>'}
        <div class="tb"><button type="button" data-mv="-1" title="Mover antes">←</button><button type="button" class="del" title="Borrar">borrar</button><button type="button" data-mv="1" title="Mover después">→</button></div>
        <button type="button" class="re">reprocesar: encajar completa</button>`, i === 0);
      const mk = d.querySelector(".mk");
      if (mk) mk.onclick = async () => { editing = await api(`/api/admin/images/${im.id}/main`, { method: "PUT" }); renderThumbs(); toast("Foto principal actualizada"); };
      d.querySelector(".del").onclick = async () => { if (!confirm("¿Borrar esta foto?")) return; await api(`/api/admin/images/${im.id}`, { method: "DELETE" }); editing.images.splice(i, 1); renderThumbs(); };
      d.querySelectorAll("[data-mv]").forEach(b => b.onclick = async () => { const j = i + +b.dataset.mv; if (j < 0 || j >= editing.images.length) return; [editing.images[i], editing.images[j]] = [editing.images[j], editing.images[i]]; await api(`/api/admin/products/${editing.id}/images/reorder`, { method: "PUT", body: JSON.stringify({ ids: editing.images.map(x => x.id) }) }); renderThumbs(); });
      const re = d.querySelector(".re"); let mode = "contain";
      re.onclick = async () => { const fd = new FormData(); fd.append("mode", mode); await api(`/api/admin/images/${im.id}/reprocess`, { method: "POST", body: fd }); mode = mode === "contain" ? "cover" : "contain"; re.textContent = "reprocesar: " + (mode === "contain" ? "encajar completa" : "recortar al centro"); toast("Foto reprocesada"); renderThumbs(); };
      wrap.appendChild(d);
    });
  }

  // Todavía no hay prenda, así que las fotos viven en el navegador: se ven, se ordenan y
  // se elige la principal igual, y recién al guardar viajan al servidor.
  function thumbsPendientes(wrap) {
    pendientes.fotos.forEach((f, i) => {
      const d = marco(`<img src="${f.preview}" alt="">
        ${i === 0 ? '<span class="first">Principal</span>' : '<button type="button" class="mk">Hacer principal</button>'}
        <div class="tb"><button type="button" data-mv="-1" title="Mover antes">←</button><button type="button" class="del" title="Quitar">quitar</button><button type="button" data-mv="1" title="Mover después">→</button></div>
        <span class="pend">se sube al guardar</span>`, i === 0);
      const mk = d.querySelector(".mk");
      if (mk) mk.onclick = () => { pendientes.fotos.unshift(pendientes.fotos.splice(i, 1)[0]); renderThumbs(); };
      d.querySelector(".del").onclick = () => { URL.revokeObjectURL(f.preview); pendientes.fotos.splice(i, 1); renderThumbs(); };
      d.querySelectorAll("[data-mv]").forEach(b => b.onclick = () => { const j = i + +b.dataset.mv; if (j < 0 || j >= pendientes.fotos.length) return; [pendientes.fotos[i], pendientes.fotos[j]] = [pendientes.fotos[j], pendientes.fotos[i]]; renderThumbs(); });
      wrap.appendChild(d);
    });
  }

  // tabla de talles
  function renderChart() {
    const guardada = editing && editing.size_chart;
    const hay = guardada || pendientes.tabla;
    $("#chartImg").hidden = !hay; $("#chartEmpty").hidden = !!hay; $("#chartActs").hidden = !hay;
    if (guardada) $("#chartImg").src = editing.size_chart.url + "?v=" + Date.now();
    else if (pendientes.tabla) $("#chartImg").src = pendientes.tabla.preview;
  }
  async function uploadChart(file) {
    if (!file) return;
    if (!editing) {   // queda en espera hasta que la prenda exista
      if (pendientes.tabla) URL.revokeObjectURL(pendientes.tabla.preview);
      pendientes.tabla = { file, preview: URL.createObjectURL(file) };
      renderChart(); $("#uploadStatus").hidden = false; $("#uploadStatus").textContent = "Tabla de talles lista: se sube al guardar.";
      return;
    }
    const st = $("#uploadStatus"); st.hidden = false; st.textContent = "Subiendo la tabla de talles...";
    const fd = new FormData(); fd.append("file", file);
    try { editing = await api(`/api/admin/products/${editing.id}/size-chart`, { method: "POST", body: fd }); renderChart(); st.textContent = `Tabla de talles lista (${editing.size_chart.width}×${editing.size_chart.height})`; }
    catch (ex) { st.textContent = "Error: " + ex.message; }
  }
  $("#pickChart").onclick = () => $("#chartInput").click();
  $("#replaceChart").onclick = () => $("#chartInput").click();
  $("#chartInput").onchange = (e) => { uploadChart(e.target.files[0]); e.target.value = ""; };
  $("#removeChart").onclick = async () => {
    if (!editing) { if (pendientes.tabla) { URL.revokeObjectURL(pendientes.tabla.preview); pendientes.tabla = null; renderChart(); } return; }
    if (!confirm("¿Quitar la tabla de talles de esta prenda?")) return;
    editing = await api(`/api/admin/products/${editing.id}/size-chart`, { method: "DELETE" }); renderChart(); toast("Tabla de talles quitada");
  };

  // Gemela de uploadChart pero para la galería: varias fotos de una, y si la prenda
  // todavía no existe quedan en espera con vista previa hasta que se guarde.
  async function upload(lista) {
    const files = [...(lista || [])].filter(f => !f.type || f.type.startsWith("image/"));
    if (!files.length) return;
    const plural = (n) => `${n} foto${n === 1 ? "" : "s"}`;
    const mode = ($$('input[name="imgmode"]').find(r => r.checked) || {}).value || settingsCache.image_mode || "cover";
    const st = $("#uploadStatus"); st.hidden = false;
    if (!editing) {   // quedan en espera hasta que la prenda exista
      files.forEach(f => pendientes.fotos.push({ file: f, preview: URL.createObjectURL(f), mode }));
      renderThumbs();
      st.textContent = `${plural(pendientes.fotos.length)} en espera: se suben al guardar.`;
      return;
    }
    st.textContent = `Subiendo ${plural(files.length)}...`;
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    fd.append("mode", mode);
    try {
      const out = await api(`/api/admin/products/${editing.id}/images`, { method: "POST", body: fd });
      editing.images.push(...out); renderThumbs();
      st.textContent = `${plural(out.length)} subida${out.length === 1 ? "" : "s"}`;
    } catch (ex) { st.textContent = "Error: " + ex.message; }
  }

  $("#pickFiles").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => { upload(e.target.files); e.target.value = ""; };
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => upload(e.dataTransfer.files));

  // ---------------- pedidos
  $$("#statusSeg button").forEach(b => b.onclick = () => { statusFilter = b.dataset.s; $$("#statusSeg button").forEach(x => x.classList.toggle("on", x === b)); loadOrders(); });
  async function loadOrders() {
    const orders = await api(`/api/admin/orders${statusFilter ? "?status=" + statusFilter : ""}`);
    const list = $("#olist");
    if (!orders.length) { list.innerHTML = `<div class="empty">No hay pedidos ${statusFilter ? "en este estado" : "todavía"}.</div>`; return; }
    list.innerHTML = orders.map(o => `<div class="orow" data-id="${o.id}">
      <div><div class="code">${o.code}</div><div class="date">${fmtDate(o.created_at)}</div></div>
      <div class="items"><b>${o.customer_name || "Sin nombre"}</b>${o.customer_phone ? ` · <a class="wa" href="https://wa.me/${o.customer_phone.replace(/\D/g, "")}" target="_blank">${o.customer_phone}</a>` : ""}
        ${o.items.map(i => `<div>${i.qty} × ${i.product_name}${i.size ? " · talle " + i.size : ""}${i.color ? " · " + i.color : ""} — ${money(i.unit_price * i.qty)}</div>`).join("")}</div>
      <div class="total">${money(o.total)}<small>${o.payment}</small></div>
      <select class="${o.status}">${["pendiente", "confirmado", "entregado", "cancelado"].map(s => `<option value="${s}" ${s === o.status ? "selected" : ""}>${s}</option>`).join("")}</select>
      <div class="note"><input placeholder="Nota interna (seña, envío, etc.)" value="${(o.note || "").replace(/"/g, "&quot;")}"><button type="button" class="link">guardar nota</button></div>
    </div>`).join("");
    $$(".orow").forEach(r => {
      const id = +r.dataset.id, sel = r.querySelector("select");
      sel.onchange = async () => { try { await api(`/api/admin/orders/${id}/status`, { method: "PUT", body: JSON.stringify({ status: sel.value }) }); sel.className = sel.value; toast(sel.value === "cancelado" ? "Pedido cancelado, stock devuelto" : "Estado actualizado"); loadStats(); } catch (ex) { toast(ex.message); loadOrders(); } };
      r.querySelector(".note .link").onclick = async () => { await api(`/api/admin/orders/${id}`, { method: "PUT", body: JSON.stringify({ note: r.querySelector(".note input").value }) }); toast("Nota guardada"); };
    });
  }

  // ---------------- categorías
  function catRow(c = { name: "", products: 0 }) {
    const d = document.createElement("div");
    d.className = "srow catrow";
    d.dataset.id = c.id ?? "";
    d.innerHTML = `<input value="${(c.name || "").replace(/"/g, "&quot;")}" maxlength="60" placeholder="Nombre de la categoría">
      <span class="cat-count">${c.products ? `${c.products} prenda${c.products === 1 ? "" : "s"}` : "vacía"}</span>
      <button type="button" data-mv="-1" title="Subir">↑</button>
      <button type="button" data-mv="1" title="Bajar">↓</button>
      <button type="button" class="rm" title="Quitar">×</button>`;
    d.querySelector(".rm").onclick = () => {
      if (c.products) { toast(`«${c.name}» tiene ${c.products} prenda${c.products === 1 ? "" : "s"}. Movelas antes de borrarla.`); return; }
      d.remove();
    };
    d.querySelectorAll("[data-mv]").forEach(b => b.onclick = () => {
      const dir = +b.dataset.mv, sib = dir < 0 ? d.previousElementSibling : d.nextElementSibling;
      if (!sib) return;
      dir < 0 ? d.parentNode.insertBefore(d, sib) : d.parentNode.insertBefore(sib, d);
    });
    return d;
  }
  function renderCats() {
    const wrap = $("#catRows"); wrap.innerHTML = "";
    if (!cats.length) wrap.innerHTML = `<p class="muted small">Todavía no hay categorías. Agregá la primera.</p>`;
    cats.forEach(c => wrap.appendChild(catRow(c)));
  }
  async function loadCats() {
    cats = await api("/api/admin/categories");
    renderCats();
  }
  $("#addCat").onclick = () => {
    if ($("#catRows .muted")) $("#catRows").innerHTML = "";
    $("#catRows").appendChild(catRow());
    $("#catRows").lastElementChild.querySelector("input").focus();
  };
  $("#catsForm").onsubmit = async (e) => {
    e.preventDefault(); const err = $("#catsErr"); err.hidden = true;
    const body = $$("#catRows .catrow").map(r => {
      const name = r.children[0].value.trim();
      return r.dataset.id ? { id: +r.dataset.id, name } : { name };
    }).filter(c => c.name);
    try {
      cats = await api("/api/admin/categories", { method: "PUT", body: JSON.stringify({ categories: body }) });
      await loadCats();
      toast("Categorías guardadas");
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };

  // ---------------- ajustes
  async function loadSettings() {
    await loadCats();
    refreshEventsCount();
    settingsCache = await api("/api/admin/settings");
    const f = $("#settingsForm"); Object.entries(settingsCache).forEach(([k, v]) => { if (f[k]) f[k].value = v; });
  }
  $("#settingsForm").onsubmit = async (e) => {
    e.preventDefault(); const f = $("#settingsForm"); const body = {}; [...f.elements].forEach(el => { if (el.name) body[el.name] = el.value; });
    try { await api("/api/admin/settings", { method: "PUT", body: JSON.stringify(body) }); toast("Ajustes guardados"); loadSettings(); } catch (ex) { toast(ex.message); }
  };

  $("#resetMetrics").onclick = async () => {
    const s = await api("/api/admin/stats?days=3650").catch(() => null);
    const total = s ? s.visitas + s.vistas_producto + s.lo_quiero : 0;
    if (!confirm(`¿Borrar todo el historial de métricas?\n\nSe pierden las visitas, las vistas de prenda y los agregados al carrito acumulados hasta hoy. Los pedidos, el stock y las prendas quedan intactos.\n\nNo se puede deshacer.`)) return;
    const r = await api("/api/admin/reset-metrics", { method: "POST" });
    toast(`Métricas borradas (${r.deleted} registros)`);
    await refreshEventsCount();
  };
  async function refreshEventsCount() {
    const el = $("#eventsCount");
    try {
      const s = await api("/api/admin/stats?days=3650");
      const n = s.visitas + s.vistas_producto + s.lo_quiero;
      el.textContent = n ? `Hoy hay ${s.vistas_producto} vistas de prenda y ${s.lo_quiero} agregados al carrito acumulados.` : "No hay métricas acumuladas.";
    } catch { el.textContent = ""; }
  }

  $("#pinForm").onsubmit = async (e) => {
    e.preventDefault(); const f = $("#pinForm"), err = $("#pinErr"); err.hidden = true;
    try {
      await api("/api/admin/pin", { method: "POST", body: JSON.stringify({ current_pin: f.current_pin.value, new_pin: f.new_pin.value }) });
      f.current_pin.value = f.new_pin.value = ""; toast("PIN cambiado. Las otras sesiones se cerraron.");
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };

  // ---------------- start
  async function start() {
    let me;
    try { me = await api("/api/admin/me"); } catch { showLogin(); return; }
    if (me.must_change_pin) { showGate(); return; }
    $("#login").hidden = true; $("#pinGate").hidden = true; $("#app").hidden = false;
    settingsCache = await api("/api/admin/settings").catch(() => ({}));
    showTab("resumen");
  }
  start();
})();
