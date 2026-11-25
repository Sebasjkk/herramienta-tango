// Herramienta Tango: lo comun a todas las paginas para los usuarios.
// Arma la navegacion (barra lateral en la PC, pestañas abajo en el celular),
// muestra si hay conexion con Tango, recarga la pagina cuando el programa se
// actualiza y trae utilidades para pedir datos y dar formato.
//
// Cada pagina incluye este archivo y llama a HT.iniciar("<id del modulo>").
// Para agregar un modulo nuevo se suma a MODULOS.
window.HT = (() => {
  "use strict";

  const ICONOS = {
    inicio: '<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z"/>',
    plata: '<circle cx="12" cy="12" r="8.5"/><path d="M14.8 9.2c-.5-.9-1.5-1.4-2.8-1.4-1.6 0-2.8.8-2.8 2.1 0 2.9 5.8 1.5 5.8 4.3 0 1.3-1.2 2.1-2.9 2.1-1.4 0-2.5-.6-3-1.6M12 6v1.8M12 16.3V18"/>',
    barco: '<path d="M3.5 15.5h17l-2.2 4H5.7z"/><path d="M6 15.5V10h12v5.5M9 10V6.5h6V10M12 4v2.5"/>',
    camino: '<path d="M3.5 7.5h10v9h-10zM13.5 10.5h3.8l3.2 3.2v2.8h-7"/><circle cx="7" cy="17.5" r="1.6"/><circle cx="17" cy="17.5" r="1.6"/>',
    mas: '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
    buscar: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    stock: '<path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5z"/><path d="M4 8.5 12 13l8-4.5M12 13v7"/>',
    sugerido: '<path d="M4 18.5 9.5 13l3.5 3.5L20 9.5"/><path d="M15 9.5h5v5"/>',
    precios: '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.2 7.2a1 1 0 0 1-1.4 0z"/><circle cx="8" cy="8" r="1.4"/>',
    etiquetas: '<path d="M3.5 6.5h11l6 5.5-6 5.5h-11z"/><circle cx="8" cy="12" r="1.3"/>',
    codigos: '<path d="M4 5.5v13M7 5.5v13M10.5 5.5v13M13 5.5v13M16.5 5.5v13M20 5.5v13"/>',
    pedidos: '<path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2z"/><path d="M9 8.5h6M9 12h6"/>',
    mezclas: '<path d="M9 3.5h6M10 3.5v5.2L5 18a1.6 1.6 0 0 0 1.4 2.5h11.2A1.6 1.6 0 0 0 19 18l-5-9.3V3.5"/><path d="M7.2 14h9.6"/>',
    cotizaciones: '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5M9 12.5h7M9 16h5"/>',
    usuarios: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.4c1.6.7 2.6 2.2 3 4.6"/>',
    persona: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c.8-3.9 3.7-6 7.5-6s6.7 2.1 7.5 6"/>',
  };
  // grupo: titulo de la seccion del menu (los modulos de un grupo van seguidos)
  // movil: va en la barra de abajo del celular; el resto queda en "Más"
  const MODULOS = [
    { id: "inicio", titulo: "Inicio", corto: "Inicio", href: "/", icono: "inicio", movil: true },
    { id: "buscar", titulo: "Buscar artículo", corto: "Buscar", href: "/buscar", icono: "buscar", movil: true },
    { id: "clientes", grupo: "Ventas", titulo: "Clientes", corto: "Clientes", href: "/clientes", icono: "usuarios" },
    { id: "pedidos", grupo: "Ventas", titulo: "Pedidos", corto: "Pedidos", href: "/pedidos", icono: "pedidos" },
    { id: "cotizaciones", grupo: "Ventas", titulo: "Cotizaciones", corto: "Cotiz.", href: "/cotizaciones", icono: "cotizaciones" },
    { id: "precios", grupo: "Ventas", titulo: "Listas de precios", corto: "Precios", href: "/precios", icono: "precios" },
    { id: "precio-sugerido", grupo: "Ventas", titulo: "Precio sugerido", corto: "Sugerido", href: "/precio-sugerido", icono: "sugerido" },
    { id: "stock", grupo: "Stock", titulo: "Stock por partida", corto: "Stock", href: "/stock", icono: "stock", movil: true },
    { id: "mezclas", grupo: "Stock", titulo: "Mezclas", corto: "Mezclas", href: "/mezclas", icono: "mezclas", movil: true },
    { id: "valorizacion", grupo: "Stock", titulo: "Valorización", corto: "Valor", href: "/valorizacion", icono: "plata" },
    { id: "etiquetas", grupo: "Stock", titulo: "Etiquetas de envío", corto: "Etiquetas", href: "/etiquetas", icono: "etiquetas" },
    { id: "carpetas", grupo: "Importaciones", titulo: "Carpetas", corto: "Carpetas", href: "/importaciones", icono: "barco" },
    { id: "en-camino", grupo: "Importaciones", titulo: "En camino", corto: "En camino", href: "/importaciones?vista=camino", icono: "camino" },
  ];

  // ---------------------------------------------------------------- tema (claro / oscuro)
  // "auto" sigue lo que tenga elegido el equipo (Windows o el celular). Cada equipo lo recuerda.
  const TEMAS = [["auto", "Automático"], ["claro", "Claro"], ["oscuro", "Oscuro"]];
  const leerTema = () => { try { return localStorage.getItem("ht_tema") || "auto"; } catch { return "auto"; } };
  const oscuroDelEquipo = window.matchMedia("(prefers-color-scheme: dark)");
  function aplicarTema(tema) {
    const raiz = document.documentElement;
    if (tema === "auto") delete raiz.dataset.tema; else raiz.dataset.tema = tema;
    const oscuro = tema === "oscuro" || (tema === "auto" && oscuroDelEquipo.matches);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = oscuro ? "#12181D" : "#0B6E69";
    for (const b of document.querySelectorAll(".tema-op")) b.setAttribute("aria-pressed", String(b.dataset.tema === tema));
  }
  function elegirTema(tema) {
    try { localStorage.setItem("ht_tema", tema); } catch {}
    aplicarTema(tema);
  }
  aplicarTema(leerTema());
  oscuroDelEquipo.addEventListener?.("change", () => aplicarTema(leerTema()));
  // Botonera Automatico / Claro / Oscuro
  function selectorTema() {
    const g = el("div", "tema");
    g.setAttribute("role", "group"); g.setAttribute("aria-label", "Tema");
    for (const [id, texto] of TEMAS) {
      const b = el("button", "tema-op", texto); b.type = "button"; b.dataset.tema = id;
      b.setAttribute("aria-pressed", String(leerTema() === id));
      b.addEventListener("click", () => elegirTema(id));
      g.append(b);
    }
    return g;
  }

  // ---------------------------------------------------------------- utilidades
  const $ = id => document.getElementById(id);
  function el(tag, clase, texto) {
    const e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto !== undefined && texto !== null) e.textContent = texto;
    return e;
  }
  const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  const sinCeros = s => (s || "").replace(/^0+/, "");
  const tokens = s => norm(s).split(/\s+/).filter(Boolean);
  const fmt = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });
  const fmtPrecio = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = n => fmt.format(n).replace("-", "−");
  const hora = d => d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false });
  // Fecha AAAA-MM-DD en formato argentino; si no es una fecha valida, el texto tal cual
  const fecha = iso => {
    if (!iso) return "";
    const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
    return isNaN(d) ? String(iso) : d.toLocaleDateString("es-AR");
  };
  const unidad = um => ({ KG: "kg", KGR: "kg", UNI: "u.", "C/U": "u.", UN: "u." })[(um || "").toUpperCase()] || (um || "").toLowerCase();

  // ---------------------------------------------------------------- datos guardados en el equipo
  // La ultima respuesta de cada consulta queda guardada (IndexedDB: entra mucho mas que en
  // localStorage). Al abrir una pantalla se muestra enseguida lo guardado, con su hora, y se
  // pide lo nuevo por detras. Si algo falla aca, simplemente no hay datos guardados.
  const GUARDADO_MAX_HORAS = 48;     // mas viejo que esto no se muestra
  let _db = null;
  function base() {
    if (_db) return _db;
    _db = new Promise(resolver => {
      try {
        const r = indexedDB.open("herramienta-tango", 1);
        r.onupgradeneeded = () => r.result.createObjectStore("respuestas");
        r.onsuccess = () => resolver(r.result);
        r.onerror = r.onblocked = () => resolver(null);
      } catch { resolver(null); }
    });
    return _db;
  }
  async function guardado(ruta) {
    const db = await base();
    if (!db) return null;
    return new Promise(resolver => {
      try {
        const r = db.transaction("respuestas").objectStore("respuestas").get(ruta);
        r.onsuccess = () => {
          const d = r.result;
          resolver(d && Date.now() - new Date(d.actualizado) < GUARDADO_MAX_HORAS * 3600e3 ? { ...d, guardado: true } : null);
        };
        r.onerror = () => resolver(null);
      } catch { resolver(null); }
    });
  }
  async function guardar(ruta, d) {
    const db = await base();
    if (!db) return;
    try { db.transaction("respuestas", "readwrite").objectStore("respuestas").put(d, ruta); } catch {}
  }

  // Los errores llevan "origen", para decir de quien es la falla:
  //   red: no se llega al programa del servidor · tango: Tango no respondio o rechazo el pedido
  //   config: falta configurar · dato: el pedido estaba mal · programa: error interno
  // opciones.previo(d): se llama enseguida con lo guardado en el equipo (d.guardado = true),
  // antes de que llegue la respuesta nueva. Sin "previo" no se usa lo guardado.
  async function pedir(ruta, forzar, opciones) {
    const previo = opciones && opciones.previo;
    if (previo && !forzar) {
      guardado(ruta).then(d => { if (d && !pedir._llego.has(ruta)) { try { previo(d); } catch (e) { console.error(e); } } });
    }
    pedir._llego.delete(ruta);
    const d = await pedirRed(ruta, forzar);
    pedir._llego.add(ruta);
    if (previo) guardar(ruta, { ok: d.ok, actualizado: d.actualizado, datos: d.datos });
    return d;
  }
  pedir._llego = new Set();

  async function pedirRed(ruta, forzar) {
    let r;
    try {
      r = await fetch(ruta + (forzar ? (ruta.includes("?") ? "&" : "?") + "refrescar=1" : ""), { cache: "no-store" });
    } catch {
      throw Object.assign(new Error("Failed to fetch"), { origen: "red" });
    }
    let d;
    try { d = await r.json(); } catch { d = { ok: false, error: `El programa respondió algo inesperado (código ${r.status}).` }; }
    if (!d.ok) {
      const origen = r.status === 502 ? "tango" : r.status === 503 ? "config" : r.status >= 500 ? "programa" : "dato";
      throw Object.assign(new Error(d.error || "Error al consultar Tango."), { origen });
    }
    return d;
  }

  const TITULOS_ERROR = {
    red: "Sin conexión con el servidor",
    tango: "Tango no respondió",
    config: "Falta configurar la Herramienta",
    programa: "Error en la Herramienta",
  };

  function textoError(e) {
    return e && (e.origen === "red" || e.message === "Failed to fetch")
      ? "No hay conexión con el programa del servidor. Revisá que estés en la red o el Wi-Fi de la oficina."
      : (e && e.message) || "Error al consultar Tango.";
  }

  // texto: string o Error (con un Error se agrega el titulo segun de quien es la falla)
  function cajaError(texto, reintentar) {
    const d = el("div", "error");
    if (texto instanceof Error) {
      const titulo = TITULOS_ERROR[texto.origen];
      if (titulo) d.append(el("strong", "error-titulo", titulo));
      texto = textoError(texto);
    }
    d.append(el("p", "", texto));
    if (reintentar) {
      const b = el("button", "boton-texto", "Volver a intentar");
      b.type = "button"; b.addEventListener("click", reintentar);
      d.append(b);
    }
    return d;
  }

  const esCelular = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent);
  const instalada = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

  function svg(nombre) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONOS[nombre]}</svg>`;
  }

  // ---------------------------------------------------------------- marco
  function armarNav(activo) {
    const nav = $("app-nav");
    nav.setAttribute("aria-label", "Secciones");
    const marca = el("a", "marca");
    marca.href = "/";
    marca.setAttribute("aria-label", "Herramienta Sianco (inicio)");
    marca.title = "Herramienta Sianco";
    // Logo de Sianco: «sianco» y el ovalo de circulos, dibujado para que se vea bien en claro y en oscuro
    marca.innerHTML = '<span class="logo-sianco">sianco' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke-linecap="round">' +
      '<path d="M7.6 19.6A9.8 9.8 0 1 1 12.9 21.8"/><path d="M9.3 16.6A6.1 6.1 0 1 1 13 18.1"/>' +
      '<path d="M10.7 14.1A2.6 2.6 0 1 1 12.6 14.6"/></g></svg></span>';
    const atajo = el("button", "atajo");
    atajo.type = "button";
    atajo.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>' +
      '<span>Buscar…</span><kbd>Ctrl K</kbd>';
    atajo.addEventListener("click", () => paleta());
    const ul = el("ul", "nav-lista");
    let grupo = null;
    for (const m of MODULOS) {
      if (m.grupo && m.grupo !== grupo) ul.append(el("li", "nav-grupo", m.grupo));
      grupo = m.grupo;
      const li = el("li", "nav-item" + (m.movil ? "" : " solo-pc"));
      const a = el("a");
      a.href = m.href;
      if (m.id === activo) a.setAttribute("aria-current", "page");
      a.innerHTML = svg(m.icono);
      a.append(el("span", "largo", m.titulo), el("span", "corto", m.corto));
      li.append(a); ul.append(li);
    }
    // Celular: los modulos que no entran en la barra van en "Más"
    const liMas = el("li", "nav-item solo-movil");
    const mas = el("a");
    mas.href = "#"; mas.setAttribute("role", "button");
    if (MODULOS.some(m => m.id === activo && !m.movil)) mas.setAttribute("aria-current", "page");
    mas.innerHTML = svg("mas");
    mas.append(el("span", "corto", "Más"));
    mas.addEventListener("click", e => { e.preventDefault(); menuMas(activo); });
    liMas.append(mas); ul.append(liMas);
    const abajo = el("div", "nav-abajo");
    const con = el("div", "conexion", "Conectando…");
    con.id = "conexion";
    const pie = el("div", "nav-pie");
    if (!instalada && !esCelular) {
      const a = el("a", "", "Acceso directo para esta PC");
      a.href = "#";
      a.addEventListener("click", e => { e.preventDefault(); ayudaAcceso(); });
      pie.append(a, el("br"));
    }
    pie.append(el("span", "", ""));
    pie.lastChild.id = "version";
    abajo.append(selectorTema(), con, pie);
    nav.replaceChildren(marca, atajo, ul, abajo);
    // Si la lista no entra en la pantalla, el degradé de abajo avisa que se puede bajar
    const marcarMas = () => ul.classList.toggle("hay-mas", ul.scrollHeight - ul.scrollTop - ul.clientHeight > 4);
    // El modulo abierto siempre a la vista (por ejemplo, En camino en una notebook), por encima del degradé.
    // Se repite si cambia el tamaño (el pie del menu crece cuando llega la version), salvo que la persona ya haya scrolleado.
    let movidoAMano = false;
    const asegurarActivo = () => {
      const act = ul.querySelector('[aria-current="page"]');
      if (!movidoAMano && act && ul.scrollHeight > ul.clientHeight) {
        const abajo = act.getBoundingClientRect().bottom - ul.getBoundingClientRect().top + ul.scrollTop;
        const margen = 44;
        if (abajo + margen > ul.scrollTop + ul.clientHeight) { ajustando = true; ul.scrollTop = abajo + margen - ul.clientHeight; }
      }
      marcarMas();
    };
    let ajustando = false;
    ul.addEventListener("scroll", () => { if (!ajustando) movidoAMano = true; ajustando = false; marcarMas(); }, { passive: true });
    if ("ResizeObserver" in window) new ResizeObserver(asegurarActivo).observe(ul);
    window.addEventListener("resize", asegurarActivo);
    requestAnimationFrame(asegurarActivo);

    // Celular: marca y conexion arriba, en una barra que se va con el scroll
    const barra = el("div", "barra-movil");
    const marca2 = marca.cloneNode(true);
    const con2 = el("div", "conexion", "");
    con2.id = "conexion-movil";
    barra.append(marca2, con2);
    const principal = document.querySelector(".app-principal");
    principal.prepend(barra);
    const aviso = el("div", "info app-aviso");
    aviso.id = "app-aviso"; aviso.hidden = true; aviso.setAttribute("role", "status");
    principal.querySelector(".pagina").prepend(aviso);
  }

  // ---------------------------------------------------------------- busqueda global (Ctrl+K)
  // Pantallas, articulos y clientes desde cualquier lado. Los datos se piden la primera vez que se abre.
  let datosPaleta = null;
  const sinTildes = t => (t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  function cargarPaleta() {
    if (datosPaleta) return datosPaleta;
    const pedir = r => fetch(r).then(x => x.json()).then(j => j.datos || []).catch(() => []);
    datosPaleta = Promise.all([pedir("/api/articulos"), pedir("/api/clientes")]);
    return datosPaleta;
  }
  function paleta() {
    if (document.querySelector("dialog.paleta")) return;
    const d = el("dialog", "paleta");
    const caja = el("div", "paleta-buscar");
    caja.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>';
    const input = el("input");
    input.type = "search"; input.placeholder = "Buscar pantalla, artículo o cliente…"; input.setAttribute("aria-label", "Buscar");
    caja.append(input, el("kbd", "", "Esc"));
    const lista = el("ul", "paleta-lista");
    lista.setAttribute("role", "listbox");
    d.append(caja, lista);
    document.body.append(d);
    const cerrar = () => { if (d.open) d.close(); d.remove(); };
    d.addEventListener("close", () => d.remove());
    d.addEventListener("click", e => { if (e.target === d) cerrar(); });
    let opciones = [], elegida = 0, articulos = [], clientes = [];
    const ir = o => { cerrar(); location.href = o.href; };
    function marcar(i) {
      elegida = Math.max(0, Math.min(i, opciones.length - 1));
      lista.querySelectorAll(".paleta-op").forEach((li, n) => li.setAttribute("aria-selected", n === elegida ? "true" : "false"));
      lista.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    }
    function pintar() {
      const q = sinTildes(input.value.trim());
      const pal = q.split(/\s+/).filter(Boolean);
      const coincide = t => pal.every(p => t.includes(p));
      const grupos = [];
      const mods = MODULOS.filter(m => !q || coincide(sinTildes(m.titulo + " " + (m.grupo || ""))))
        .map(m => ({ titulo: m.titulo, sub: m.grupo || "", href: m.href, icono: m.icono }));
      if (mods.length) grupos.push(["Pantallas", mods]);
      if (q.length >= 2) {
        const arts = articulos.filter(a => coincide(sinTildes(`${a.codigo} ${a.descripcion} ${a.sinonimo || ""} ${a.codigo_barras || ""}`))).slice(0, 8)
          .map(a => ({ titulo: a.descripcion || a.codigo, sub: a.codigo, href: "/buscar?art=" + encodeURIComponent(a.codigo), icono: "stock" }));
        if (arts.length) grupos.push(["Artículos", arts]);
        const clis = clientes.filter(c => coincide(sinTildes(`${c.codigo} ${c.razon_social} ${c.cuit || ""}`))).slice(0, 6)
          .map(c => ({ titulo: c.razon_social, sub: c.codigo, href: "/clientes?ver=" + encodeURIComponent(c.codigo), icono: "persona" }));
        if (clis.length) grupos.push(["Clientes", clis]);
        grupos.push(["Buscar en todo", [{ titulo: `Buscar «${input.value.trim()}» en artículos`, sub: "", href: "/buscar?q=" + encodeURIComponent(input.value.trim()), icono: "buscar" }]]);
      }
      opciones = [];
      lista.replaceChildren();
      for (const [nombre, ops] of grupos) {
        lista.append(el("li", "paleta-grupo", nombre));
        for (const o of ops) {
          const li = el("li", "paleta-op");
          li.setAttribute("role", "option");
          li.innerHTML = svg(o.icono);
          li.append(el("span", "", o.titulo), el("span", "sub", o.sub));
          const n = opciones.length;
          li.addEventListener("mousemove", () => { if (elegida !== n) marcar(n); });
          li.addEventListener("click", () => ir(o));
          opciones.push(o); lista.append(li);
        }
      }
      if (!opciones.length) lista.append(el("li", "paleta-vacio", "No hay nada con eso."));
      marcar(0);
    }
    input.addEventListener("input", pintar);
    input.addEventListener("keydown", e => {
      if (e.key === "ArrowDown") { e.preventDefault(); marcar(elegida + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); marcar(elegida - 1); }
      else if (e.key === "Enter" && opciones[elegida]) { e.preventDefault(); ir(opciones[elegida]); }
    });
    d.showModal();
    input.focus();
    pintar();
    cargarPaleta().then(([a, c]) => { articulos = a; clientes = c; if (d.isConnected) pintar(); });
  }
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); paleta(); }
  });

  function menuMas(activo) {
    const d = el("dialog", "hoja-mas");
    const cerrar = () => { if (d.open) d.close(); d.remove(); };
    d.addEventListener("cancel", () => setTimeout(() => d.remove(), 0));
    d.addEventListener("click", e => { if (e.target === d) cerrar(); });   // tocar afuera cierra
    const ul = el("ul", "hoja-lista");
    let grupo = null;
    for (const m of MODULOS.filter(m => !m.movil)) {
      if (m.grupo && m.grupo !== grupo) ul.append(el("li", "hoja-grupo", m.grupo));
      grupo = m.grupo;
      const a = el("a"); a.href = m.href;
      if (m.id === activo) a.setAttribute("aria-current", "page");
      a.innerHTML = svg(m.icono); a.append(el("span", "", m.titulo));
      const li = el("li"); li.append(a); ul.append(li);
    }
    const c = el("button", "boton", "Cerrar"); c.type = "button"; c.addEventListener("click", cerrar);
    const t = el("div", "hoja-tema"); t.append(el("span", "hoja-grupo", "Tema"), selectorTema());
    d.append(ul, t, c);
    document.body.append(d);
    d.showModal();
  }

  // Renglones grises mientras cargan los datos (con la forma de una lista)
  function esqueleto(filas = 6, clase = "") {
    const d = el("div", "esqueleto " + clase);
    d.setAttribute("aria-hidden", "true");
    for (let i = 0; i < filas; i++) {
      const f = el("div", "esq-fila");
      f.append(el("span", "esq esq-corta"), el("span", "esq esq-larga"), el("span", "esq esq-num"));
      d.append(f);
    }
    return d;
  }

  // Mensaje breve abajo de la pantalla. accion: { texto, alTocar } agrega un boton (por ejemplo "Deshacer")
  function avisar(texto, accion, segundos) {
    let t = $("ht-aviso-breve");
    if (!t) { t = el("div", "aviso-breve"); t.id = "ht-aviso-breve"; t.setAttribute("role", "status"); document.body.append(t); }
    t.replaceChildren(el("span", "", texto));
    if (accion) {
      const b = el("button", "", accion.texto); b.type = "button";
      b.addEventListener("click", () => { t.classList.remove("visible"); accion.alTocar(); });
      t.append(b);
    }
    t.classList.toggle("con-accion", !!accion);
    t.classList.add("visible");
    clearTimeout(avisar.t);
    avisar.t = setTimeout(() => t.classList.remove("visible"), (segundos || (accion ? 10 : 2.6)) * 1000);
  }

  // Texto de la cabecera: "Datos de Tango de las 16:40 h" (con "actualizando…" si es lo guardado)
  function textoDatos(d) {
    if (!d) return "Sin datos";
    const t = "Datos de Tango de las " + hora(new Date(d.actualizado)) + " h";
    const dia = new Date(d.actualizado).toDateString() !== new Date().toDateString() ? " del " + new Date(d.actualizado).toLocaleDateString("es-AR") : "";
    return d.guardado ? t.replace(" h", " h" + dia) + " · actualizando…" : t;
  }

  // ---------------------------------------------------------------- exportar a Excel
  // columnas: [["Titulo", "texto" | "numero"], ...]; filas: arrays con los valores en ese orden.
  // El servidor arma el .xlsx (la Herramienta no usa librerias).
  async function exportar(nombre, columnas, filas) {
    avisar("Armando el Excel…");
    try {
      const r = await fetch("/api/exportar", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre, columnas: columnas.map(c => ({ titulo: c[0], tipo: c[1] || "texto" })), filas }) });
      if (!r.ok) { let m = "No se pudo armar el Excel."; try { m = (await r.json()).error || m; } catch {} throw new Error(m); }
      const blob = await r.blob();
      const a = el("a"); a.href = URL.createObjectURL(blob);
      a.download = nombre.replace(/[\\/:*?"<>|]+/g, " ").trim() + ".xlsx";
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      avisar("Excel descargado");
    } catch (e) { avisar(e.message || "No se pudo armar el Excel."); }
  }
  // Nombre del cliente que lleva a su ficha
  function linkCliente(codigo, nombre) {
    const d = el("div", "cli");
    if (!codigo) { d.textContent = nombre || ""; return d; }
    const a = el("a", "", nombre || codigo); a.href = "/clientes?ver=" + encodeURIComponent(codigo.trim());
    a.style.color = "inherit";
    d.append(a);
    return d;
  }

  function botonExportar(alTocar, texto) {
    const b = el("button", "boton chico", texto || "Exportar a Excel"); b.type = "button";
    b.addEventListener("click", alTocar);
    return b;
  }

  // Copia el link a algo puntual (un articulo, un pedido) para mandarlo por WhatsApp o mail
  async function copiarLink(ruta) {
    const url = location.origin + ruta;
    try {
      if (navigator.share && esCelular) { await navigator.share({ url }); return; }
    } catch (e) { if (e && e.name === "AbortError") return; }
    try {
      await navigator.clipboard.writeText(url);
      avisar("Link copiado");
    } catch {
      // Sin HTTPS algunos navegadores no dejan usar el portapapeles: se muestra para copiar a mano
      prompt("Copiá el link:", url);
    }
  }

  // Como crear el acceso directo con el icono de la Herramienta: lo hace el
  // navegador (toma el icono del manifest y abre en una ventana propia, sin pestañas)
  function ayudaAcceso() {
    let d = $("ayuda-acceso");
    if (!d) {
      d = el("dialog", "ayuda");
      d.id = "ayuda-acceso";
      d.innerHTML = `
        <h2>Acceso directo en esta PC</h2>
        <p>Queda en el escritorio con el ícono de la Herramienta y se abre como una aplicación, sin pestañas.</p>
        <h3>En Chrome</h3>
        <ol>
          <li>Tocá el menú <b>⋮</b> (arriba a la derecha).</li>
          <li>Elegí <b>Transmitir, guardar y compartir</b> y después <b>Crear acceso directo…</b><br>
              <small>En versiones viejas está en <b>Más herramientas</b>.</small></li>
          <li>Tildá <b>Abrir como ventana</b> y tocá <b>Crear</b>.</li>
        </ol>
        <h3>En Edge</h3>
        <ol>
          <li>Tocá el menú <b>⋯</b> y elegí <b>Aplicaciones</b>.</li>
          <li>Elegí <b>Instalar este sitio como aplicación</b> y tocá <b>Instalar</b>.</li>
        </ol>
        <form method="dialog"><button class="boton">Listo</button></form>`;
      document.body.append(d);
    }
    d.showModal();
  }

  const ESTADOS = {
    ok: ["ok", "Conectado a Tango"],
    sin_conexion: ["mal", "Sin conexión con Tango"],
    token_invalido: ["mal", "Tango rechazó el token"],
    sin_configurar: ["mal", "Falta configurar el servidor"],
  };

  let versionInicial = null;
  async function revisarEstado() {
    const aviso = $("app-aviso");
    const pintar = (clase, texto) => {
      for (const id of ["conexion", "conexion-movil"]) {
        const c = $(id);
        if (!c) continue;
        c.className = "conexion " + clase;
        c.textContent = id === "conexion-movil" ? (clase === "ok" ? "" : texto) : texto;
        c.title = texto;
      }
    };
    try {
      const r = await fetch("/api/estado", { cache: "no-store" });
      const e = await r.json();
      if (versionInicial && e.version !== versionInicial) { location.reload(); return; }
      versionInicial = versionInicial || e.version;
      $("version").textContent = "Versión " + e.version;
      const [clase, texto] = ESTADOS[!e.configurado ? "sin_configurar" : e.tango] || ["", "Conectando…"];
      pintar(clase, texto);
      const a = e.actualizacion || {};
      const instalando = a.estado === "instalando" || a.estado === "reiniciando";
      aviso.hidden = !instalando;
      if (instalando) aviso.textContent = `Instalando la versión ${a.version_disponible}. La página vuelve sola en unos segundos.`;
    } catch {
      pintar("mal", "Sin conexión con el servidor");
      if (!aviso.hidden) aviso.textContent = "Reiniciando el programa con la versión nueva…";
    }
  }

  // ---------------------------------------------------------------- quien modifica
  // Sin claves: cualquiera de la red puede modificar. Cada equipo recuerda un nombre
  // (se pregunta la primera vez) que va al registro de cambios junto con la IP.
  const leerNombre = () => { try { return localStorage.getItem("ht_nombre") || ""; } catch { return ""; } };
  const guardarNombre = n => { try { localStorage.setItem("ht_nombre", n); } catch {} };
  let nombrePreguntado = false;

  async function escribir(ruta, datos) {
    if (!leerNombre() && !nombrePreguntado) await pedirNombre(true);
    const r = await fetch(ruta, { method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Nombre": encodeURIComponent(leerNombre()) },
      body: JSON.stringify(datos || {}) });
    let d;
    try { d = await r.json(); } catch { d = { ok: false, error: "Respuesta inválida del servidor." }; }
    if (!d.ok) throw new Error(d.error || d.mensaje || "No se pudo guardar.");
    return d;
  }

  // Ventana (dialog) armada en el momento; se borra al cerrarse
  function ventana(titulo, armar) {
    const d = el("dialog", "ayuda");
    d.append(el("h2", "", titulo));
    const cerrar = () => { if (d.open) d.close(); d.remove(); };
    d.addEventListener("cancel", () => setTimeout(() => d.remove(), 0));
    document.body.append(d);
    armar(d, cerrar);
    d.showModal();
    return d;
  }

  function campo(d, etiqueta, atributos) {
    const id = "c" + Math.random().toString(36).slice(2, 8);
    const l = el("label", "etiqueta", etiqueta); l.htmlFor = id;
    const i = el("input", "campo"); i.id = id;
    Object.assign(i, atributos || {});
    d.append(l, i);
    return i;
  }

  function botones(d, textoOk, cerrar, peligro) {
    const err = el("p", "mensaje-error"); err.hidden = true;
    const acc = el("div", "acciones");
    if (cerrar) { const c = el("button", "boton", "Cancelar"); c.type = "button"; c.addEventListener("click", cerrar); acc.append(c); }
    const ok = el("button", "boton " + (peligro ? "peligro confirmar" : "primario"), textoOk); ok.type = "submit";
    acc.append(ok);
    d.append(err, acc);
    return { ok, error: t => { err.textContent = t; err.hidden = !t; } };
  }

  // Devuelve una promesa que se resuelve al cerrar (con o sin nombre)
  function pedirNombre(primeraVez) {
    nombrePreguntado = true;
    return new Promise(resolver => {
      ventana(primeraVez ? "¿Quién está haciendo el cambio?" : "Tu nombre", (d, cerrar) => {
        d.append(el("p", "", "Queda en el registro de cambios. Este equipo lo recuerda; no se vuelve a preguntar."));
        const f = el("form");
        const n = campo(f, "Nombre", { autocomplete: "name", value: leerNombre(), maxLength: 40 });
        const acc = el("div", "acciones");
        const saltar = el("button", "boton", "Seguir sin nombre"); saltar.type = "button";
        const ok = el("button", "boton primario", "Listo"); ok.type = "submit";
        acc.append(saltar, ok); f.append(acc);
        const fin = () => { cerrar(); avisarNombre(); resolver(); };
        saltar.addEventListener("click", fin);
        d.addEventListener("cancel", fin);
        f.addEventListener("submit", e => { e.preventDefault(); guardarNombre(n.value.trim()); fin(); });
        d.append(f);
        setTimeout(() => n.focus(), 50);
      });
    });
  }

  const oyentes = [];
  function avisarNombre() { for (const f of oyentes) { try { f(leerNombre()); } catch (e) { console.error(e); } } }

  function iniciar(activo) {
    armarNav(activo);
    revisarEstado();
    setInterval(revisarEstado, 15000);
  }

  // Buscador con boton para borrar
  function conectarBuscador(input, botonLimpiar, alCambiar) {
    let espera;
    const actualizar = () => { botonLimpiar.hidden = !input.value; };
    input.addEventListener("input", () => { actualizar(); clearTimeout(espera); espera = setTimeout(alCambiar, 120); });
    botonLimpiar.addEventListener("click", () => { input.value = ""; actualizar(); alCambiar(); input.focus(); });
    actualizar();
  }

  return { MODULOS, $, el, norm, sinCeros, tokens, fmt, fmtPrecio, num, hora, fecha, unidad, pedir, textoError,
           cajaError, esCelular, instalada, iniciar, conectarBuscador, svg, esqueleto, avisar, copiarLink, textoDatos, exportar, botonExportar, guardado, linkCliente,
           // quien modifica
           nombre: leerNombre, pedirNombre: () => pedirNombre(false), alCambiarNombre: f => oyentes.push(f),
           escribir, ventana, campo, botones };
})();
