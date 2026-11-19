// Codigo de barras Code-128 (sets B y C), dibujado como SVG en milimetros.
// Uso: Codigo128.svg("1000089", { modulo: 0.375, alto: 10 })  -> elemento <svg>
//      Codigo128.modulos("1000089")                          -> "11010010000..." (1 = barra)
(function (global) {
  "use strict";

  // Anchos barra/espacio de cada simbolo (0 a 106; el 106 es el de parada)
  const PATRONES = (
    "212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 " +
    "221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 " +
    "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 " +
    "212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 " +
    "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 " +
    "231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 " +
    "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 " +
    "112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 " +
    "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 " +
    "214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 " +
    "114131 311141 411131 211412 211214 211232 2331112").split(" ");
  const INICIO_B = 104, INICIO_C = 105, A_C = 99, A_B = 100, PARADA = 106;

  const esDigito = c => c >= "0" && c <= "9";
  function digitosDesde(s, i) { let j = i; while (j < s.length && esDigito(s[j])) j++; return j - i; }

  // Valores de los simbolos, sin verificador ni parada. Usa C para tiras de digitos
  // (achica el codigo a la mitad) y B para lo demas.
  function valores(texto) {
    const s = String(texto);
    if (!s.length) throw new Error("Texto vacío");
    for (const c of s) {
      const n = c.charCodeAt(0);
      if (n < 32 || n > 126) throw new Error(`El carácter «${c}» no se puede poner en el código`);
    }
    const v = [];
    let i = 0, set;
    const inicio = digitosDesde(s, 0);
    if (inicio >= 4 || (inicio === s.length && inicio >= 2)) { set = "C"; v.push(INICIO_C); }
    else { set = "B"; v.push(INICIO_B); }
    while (i < s.length) {
      if (set === "C") {
        if (digitosDesde(s, i) >= 2) { v.push(Number(s.substr(i, 2))); i += 2; continue; }
        set = "B"; v.push(A_B);
        continue;
      }
      const run = digitosDesde(s, i);
      const alFinal = i + run === s.length;
      if (run >= 6 || (alFinal && run >= 4)) {
        if (run % 2) { v.push(s.charCodeAt(i) - 32); i++; }    // el impar va en B
        set = "C"; v.push(A_C);
        continue;
      }
      v.push(s.charCodeAt(i) - 32); i++;
    }
    let suma = v[0];
    for (let k = 1; k < v.length; k++) suma += v[k] * k;
    v.push(suma % 103, PARADA);
    return v;
  }

  function modulos(texto) {
    let out = "";
    for (const val of valores(texto)) {
      const p = PATRONES[val];
      for (let k = 0; k < p.length; k++) out += (k % 2 ? "0" : "1").repeat(Number(p[k]));
    }
    return out;
  }

  // opciones: modulo (mm por barra minima), alto (mm), silencio (modulos de margen a cada lado)
  function svg(texto, opciones) {
    const o = Object.assign({ modulo: 0.375, alto: 10, silencio: 10 }, opciones || {});
    const m = modulos(texto);
    const ancho = m.length + 2 * o.silencio;
    const NS = "http://www.w3.org/2000/svg";
    const e = document.createElementNS(NS, "svg");
    e.setAttribute("viewBox", `0 0 ${ancho} 1`);
    e.setAttribute("preserveAspectRatio", "none");
    e.setAttribute("shape-rendering", "crispEdges");
    e.setAttribute("width", (ancho * o.modulo).toFixed(3) + "mm");
    e.setAttribute("height", o.alto + "mm");
    e.setAttribute("role", "img");
    e.setAttribute("aria-label", "Código de barras " + texto);
    let d = "";
    for (let i = 0; i < m.length;) {
      if (m[i] === "1") { let j = i; while (m[j] === "1") j++; d += `M${i + o.silencio} 0h${j - i}v1h-${j - i}z`; i = j; }
      else i++;
    }
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    e.append(p);
    return e;
  }

  // Ancho total en modulos, contando los margenes de silencio
  const largo = (texto, silencio = 10) => modulos(texto).length + 2 * silencio;

  global.Codigo128 = { valores, modulos, svg, largo };
})(typeof window !== "undefined" ? window : globalThis);
