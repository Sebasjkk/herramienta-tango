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
    buscar: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    stock: '<path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5z"/><path d="M4 8.5 12 13l8-4.5M12 13v7"/>',
    precios: '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.2 7.2a1 1 0 0 1-1.4 0z"/><circle cx="8" cy="8" r="1.4"/>',
    cotizaciones: '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5M9 12.5h7M9 16h5"/>',
    usuarios: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.4c1.6.7 2.6 2.2 3 4.6"/>',
    persona: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c.8-3.9 3.7-6 7.5-6s6.7 2.1 7.5 6"/>',
  };
  const MODULOS = [
    { id: "inicio", titulo: "Buscar artículo", corto: "Buscar", href: "/", icono: "buscar" },
    { id: "stock", titulo: "Stock por partida", corto: "Stock", href: "/stock", icono: "stock" },
    { id: "precios", titulo: "Listas de precios", corto: "Precios", href: "/precios", icono: "precios" },
    { id: "cotizaciones", titulo: "Cotizaciones", corto: "Cotiz.", href: "/cotizaciones", icono: "cotizaciones" },
    { id: "usuarios", titulo: "Perfiles", corto: "Perfiles", href: "/usuarios", icono: "usuarios", soloAdmin: true },
  ];

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
  const fecha = iso => iso ? new Date(iso + "T00:00:00").toLocaleDateString("es-AR") : "";
  const unidad = um => ({ KG: "kg", KGR: "kg", UNI: "u.", "C/U": "u.", UN: "u." })[(um || "").toUpperCase()] || (um || "").toLowerCase();

  async function pedir(ruta, forzar) {
    const r = await fetch(ruta + (forzar ? (ruta.includes("?") ? "&" : "?") + "refrescar=1" : ""), { cache: "no-store" });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "Error al consultar Tango.");
    return d;
  }

  function textoError(e) {
    return e && e.message === "Failed to fetch"
      ? "No hay conexión con el programa del servidor. Revisá que estés en la red o el Wi-Fi de la oficina."
      : (e && e.message) || "Error al consultar Tango.";
  }

  function cajaError(texto, reintentar) {
    const d = el("div", "error");
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
    marca.innerHTML = '<img src="/icono-192.png" alt=""> <div>Herramienta <span>Tango</span></div>';
    const ul = el("ul", "nav-lista");
    for (const m of MODULOS) {
      const li = el("li", "nav-item");
      if (m.soloAdmin) { li.dataset.soloAdmin = "1"; li.hidden = true; }
      const a = el("a");
      a.href = m.href;
      if (m.id === activo) a.setAttribute("aria-current", "page");
      a.innerHTML = svg(m.icono);
      a.append(el("span", "largo", m.titulo), el("span", "corto", m.corto));
      li.append(a); ul.append(li);
    }
    const abajo = el("div", "nav-abajo");
    const cuenta = el("div", "cuenta"); cuenta.id = "cuenta";
    abajo.append(cuenta);
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
    abajo.append(con, pie);
    nav.replaceChildren(marca, ul, abajo);

    // Celular: marca y conexion arriba, en una barra que se va con el scroll
    const barra = el("div", "barra-movil");
    const marca2 = marca.cloneNode(true);
    const con2 = el("div", "conexion", "");
    con2.id = "conexion-movil";
    const derecha = el("div", "barra-movil-der");
    const cuenta2 = el("div", "cuenta"); cuenta2.id = "cuenta-movil";
    derecha.append(con2, cuenta2);
    barra.append(marca2, derecha);
    const principal = document.querySelector(".app-principal");
    principal.prepend(barra);
    const aviso = el("div", "info app-aviso");
    aviso.id = "app-aviso"; aviso.hidden = true; aviso.setAttribute("role", "status");
    principal.querySelector(".pagina").prepend(aviso);
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

  // ---------------------------------------------------------------- perfiles
  // El token de la sesion se guarda en el navegador; el servidor sabe de quien es.
  let sesion = { usuario: null, nombres: [] };
  const oyentes = [];
  const leerToken = () => { try { return localStorage.getItem("ht_sesion") || ""; } catch { return ""; } };
  const guardarToken = t => { try { t ? localStorage.setItem("ht_sesion", t) : localStorage.removeItem("ht_sesion"); } catch {} };

  function avisarSesion() {
    const u = sesion.usuario;
    for (const li of document.querySelectorAll("[data-solo-admin]")) li.hidden = !(u && u.rol === "administrador");
    for (const id of ["cuenta", "cuenta-movil"]) dibujarCuenta($(id), id === "cuenta-movil");
    for (const f of oyentes) { try { f(u); } catch (e) { console.error(e); } }
  }

  function dibujarCuenta(c, movil) {
    if (!c) return;
    c.replaceChildren();
    const u = sesion.usuario;
    if (u) {
      const quien = el("button", "cuenta-quien"); quien.type = "button";
      quien.innerHTML = svg("persona");
      quien.append(el("span", "", u.nombre));
      quien.title = u.rol === "administrador" ? "Administrador" : "Usuario";
      quien.addEventListener("click", menuCuenta);
      c.append(quien);
    } else if (sesion.nombres.length) {
      const b = el("button", "boton chico", "Entrar"); b.type = "button";
      b.addEventListener("click", () => entrar());
      c.append(b);
    }
  }

  async function revisarSesion() {
    try {
      const r = await fetch("/api/sesion", { cache: "no-store", headers: { "X-Sesion": leerToken() } });
      const d = await r.json();
      sesion = { usuario: d.usuario, nombres: d.nombres || [] };
      if (!d.usuario) guardarToken("");
    } catch { sesion = { usuario: null, nombres: [] }; }
    avisarSesion();
    if (sesion.usuario && sesion.usuario.debe_cambiar) cambiarClave(true);
  }

  async function escribir(ruta, datos) {
    const r = await fetch(ruta, { method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Sesion": leerToken() }, body: JSON.stringify(datos || {}) });
    let d;
    try { d = await r.json(); } catch { d = { ok: false, error: "Respuesta inválida del servidor." }; }
    if (r.status === 401) await revisarSesion();
    if (!d.ok) throw new Error(d.error || d.mensaje || "No se pudo guardar.");
    return d;
  }

  async function pedirConSesion(ruta) {
    const r = await fetch(ruta, { cache: "no-store", headers: { "X-Sesion": leerToken() } });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "No se pudo consultar.");
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

  function entrar() {
    ventana("Entrar", (d, cerrar) => {
      d.append(el("p", "", "Para modificar precios. Mirar no necesita entrar."));
      const f = el("form");
      const l = el("label", "etiqueta", "Quién sos"); l.htmlFor = "ent-nombre";
      const sel = el("select", "campo"); sel.id = "ent-nombre";
      let ultimo = ""; try { ultimo = localStorage.getItem("ht_nombre") || ""; } catch {}
      for (const n of sesion.nombres) { const o = el("option", "", n); o.value = n; o.selected = n === ultimo; sel.append(o); }
      f.append(l, sel);
      const clave = campo(f, "Clave", { type: "password", autocomplete: "current-password", required: true });
      const b = botones(f, "Entrar", cerrar);
      f.addEventListener("submit", async e => {
        e.preventDefault(); b.ok.disabled = true; b.error("");
        try {
          const r = await fetch("/api/sesion", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nombre: sel.value, clave: clave.value }) });
          const res = await r.json();
          if (!res.ok) throw new Error(res.mensaje);
          guardarToken(res.token);
          try { localStorage.setItem("ht_nombre", sel.value); } catch {}
          sesion.usuario = res.usuario; cerrar(); avisarSesion();
          if (res.usuario.debe_cambiar) cambiarClave(true);
        } catch (ex) { b.error(ex.message); b.ok.disabled = false; }
      });
      d.append(f);
      setTimeout(() => clave.focus(), 50);
    });
  }

  function cambiarClave(obligatorio) {
    if (document.getElementById("ventana-clave")) return;
    const v = ventana(obligatorio ? "Elegí tu clave" : "Cambiar mi clave", (d, cerrar) => {
      d.id = "ventana-clave";
      if (obligatorio) d.append(el("p", "", "Estás usando una clave inicial. Elegí una propia: solo vos la vas a saber."));
      const f = el("form");
      const actual = campo(f, obligatorio ? "Clave inicial (la que te dieron)" : "Clave actual", { type: "password", autocomplete: "current-password", required: true });
      const nueva = campo(f, "Clave nueva (6 o más caracteres)", { type: "password", autocomplete: "new-password", required: true, minLength: 6 });
      const repetir = campo(f, "Repetí la clave nueva", { type: "password", autocomplete: "new-password", required: true });
      const b = botones(f, "Guardar clave", obligatorio ? null : cerrar);
      f.addEventListener("submit", async e => {
        e.preventDefault(); b.error("");
        if (nueva.value !== repetir.value) { b.error("Las dos claves nuevas no coinciden."); return; }
        b.ok.disabled = true;
        try {
          const r = await escribir("/api/sesion/clave", { actual: actual.value, nueva: nueva.value });
          sesion.usuario = r.usuario; cerrar(); avisarSesion();
        } catch (ex) { b.error(ex.message); b.ok.disabled = false; }
      });
      d.append(f);
      if (obligatorio) {
        const salir = el("button", "boton-texto", "Salir sin cambiarla"); salir.type = "button";
        salir.addEventListener("click", async () => { await cerrarSesion(); cerrar(); });
        d.append(salir);
        d.addEventListener("cancel", e => e.preventDefault());
      }
      setTimeout(() => actual.focus(), 50);
    });
    return v;
  }

  async function cerrarSesion() {
    try { await escribir("/api/sesion/salir", {}); } catch {}
    guardarToken(""); sesion.usuario = null; avisarSesion();
  }

  function menuCuenta() {
    const u = sesion.usuario;
    ventana(u.nombre, (d, cerrar) => {
      d.append(el("p", "", u.rol === "administrador"
        ? "Administrador: modifica precios, crea y elimina listas, y maneja los perfiles."
        : "Usuario: puede modificar precios. Crear o eliminar listas lo hace un administrador."));
      const acc = el("div", "acciones");
      const clave = el("button", "boton", "Cambiar mi clave"); clave.type = "button";
      clave.addEventListener("click", () => { cerrar(); cambiarClave(false); });
      const salir = el("button", "boton", "Salir"); salir.type = "button";
      salir.addEventListener("click", async () => { await cerrarSesion(); cerrar(); });
      const listo = el("button", "boton primario", "Listo"); listo.type = "button"; listo.addEventListener("click", cerrar);
      acc.append(clave, salir, listo);
      d.append(acc);
    });
  }

  function iniciar(activo) {
    armarNav(activo);
    revisarEstado();
    revisarSesion();
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
           cajaError, esCelular, instalada, iniciar, conectarBuscador, svg,
           // perfiles
           usuario: () => sesion.usuario, esAdmin: () => !!(sesion.usuario && sesion.usuario.rol === "administrador"),
           alCambiarSesion: f => oyentes.push(f), entrar, cambiarClave, escribir, pedirConSesion, ventana, campo, botones };
})();
