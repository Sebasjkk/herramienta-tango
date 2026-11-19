// Etiquetas de 100 x 50 mm con el codigo de articulo de Tango y, si tiene, el numero de partida.
// Necesita codigo128.js y etiqueta-codigo.css.
//   EtiquetaCodigo.barras(texto, alto)       -> <svg> del codigo
//   EtiquetaCodigo.etiqueta({codigo, descripcion, partida})
//   EtiquetaCodigo.imprimir([{codigo, descripcion, partida, cantidad}])
//   EtiquetaCodigo.tanda: leer(), agregar(lista), quitar(i), vaciar(), alCambiar(fn)
window.EtiquetaCodigo = (() => {
  "use strict";
  const ANCHO_UTIL = 92;              // mm para el codigo (100 - margenes)
  const CLAVE_TANDA = "ht_codigos_tanda";

  function nodo(tag, clase, texto) {
    const e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto != null) e.textContent = texto;
    return e;
  }

  function barras(texto, alto) {
    const largo = Codigo128.largo(texto);
    // 0,375 y 0,25 mm = 3 y 2 puntos de la Zebra (203 dpi)
    const modulo = [0.375, 0.25, 0.2].find(m => largo * m <= ANCHO_UTIL + 7.5) || 0.2;
    const svg = Codigo128.svg(texto, { modulo, alto });
    svg.style.marginLeft = `-${(10 * modulo).toFixed(2)}mm`;   // el margen blanco cae sobre el borde de la etiqueta
    return svg;
  }

  function etiqueta(x) {
    const e = nodo("div", "cb" + (x.partida ? "" : " sola"));
    e.append(nodo("div", "cb-des", x.descripcion));
    const b1 = nodo("div", "cb-bloque");
    const t1 = nodo("div", "cb-txt"); t1.append("Artículo ", nodo("b", "", x.codigo));
    b1.append(barras(x.codigo, x.partida ? 12.5 : 24), t1);
    e.append(b1);
    if (x.partida) {
      const b2 = nodo("div", "cb-bloque");
      const t2 = nodo("div", "cb-txt"); t2.append("Partida ", nodo("b", "", x.partida));
      b2.append(barras(x.partida, 12.5), t2);
      e.append(b2);
    }
    return e;
  }

  // Muestra la etiqueta achicada para que entre en el contenedor
  function vista(contenedor, x) {
    const e = etiqueta(x);
    contenedor.classList.add("vista-cb");
    contenedor.replaceChildren(e);
    const escala = Math.min(1.2, (contenedor.clientWidth - 4) / 378);   // 100 mm ≈ 378 px
    e.style.transform = `scale(${escala})`;
    contenedor.style.height = Math.ceil(189 * escala + 10) + "px";
  }

  const total = lista => lista.reduce((s, x) => s + (x.cantidad || 0), 0);

  function imprimir(lista) {
    if (!total(lista)) return;
    let cont = document.getElementById("impresion-cb");
    if (!cont) { cont = nodo("div"); cont.id = "impresion-cb"; document.body.append(cont); }
    const hojas = [];
    for (const x of lista) for (let i = 0; i < x.cantidad; i++) hojas.push(etiqueta(x));
    cont.replaceChildren(...hojas);
    window.print();
  }

  // Tanda: etiquetas de varios articulos para imprimir juntas (queda guardada en el equipo)
  const oyentes = [];
  function leer() { try { return JSON.parse(localStorage.getItem(CLAVE_TANDA)) || []; } catch { return []; } }
  function guardar(t) { try { localStorage.setItem(CLAVE_TANDA, JSON.stringify(t)); } catch {} oyentes.forEach(f => f(t)); }
  const tanda = {
    leer,
    agregar(lista) {
      const t = leer();
      for (const x of lista) {
        if (!(x.cantidad > 0)) continue;
        const y = t.find(z => z.codigo === x.codigo && z.partida === x.partida);
        if (y) y.cantidad += x.cantidad; else t.push({ codigo: x.codigo, descripcion: x.descripcion, partida: x.partida, cantidad: x.cantidad });
      }
      guardar(t);
    },
    quitar(i) { const t = leer(); t.splice(i, 1); guardar(t); },
    vaciar() { guardar([]); },
    alCambiar(f) { oyentes.push(f); },
  };
  window.addEventListener("storage", e => { if (e.key === CLAVE_TANDA) oyentes.forEach(f => f(leer())); });

  return { barras, etiqueta, vista, imprimir, total, tanda };
})();
