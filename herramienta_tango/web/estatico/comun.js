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
      const a = el("a");
      a.href = m.href;
      if (m.id === activo) a.setAttribute("aria-current", "page");
      a.innerHTML = svg(m.icono);
      a.append(el("span", "largo", m.titulo), el("span", "corto", m.corto));
      li.append(a); ul.append(li);
    }
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
    abajo.append(con, pie);
    nav.replaceChildren(marca, ul, abajo);

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
           cajaError, esCelular, instalada, iniciar, conectarBuscador, svg,
           // quien modifica
           nombre: leerNombre, pedirNombre: () => pedirNombre(false), alCambiarNombre: f => oyentes.push(f),
           escribir, ventana, campo, botones };
})();
