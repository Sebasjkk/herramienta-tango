/*
 * Lectura de codigos de barras desde una foto (Escaner.leerFoto).
 *
 * Por que una foto y no la camara en vivo: los navegadores solo dejan usar la camara en vivo en
 * paginas seguras (https), y la Herramienta se abre por http en la red de la oficina. Sacar una
 * foto (input type=file con capture) funciona igual en Android y en iPhone.
 *
 * Usa ZXing (zxing.min.js, Apache 2.0), que se carga recien la primera vez que se escanea. ZXing
 * lee un codigo por imagen: para las etiquetas con dos (articulo y partida) se recorre la foto por
 * franjas horizontales (y girada, por si la foto se saco de costado) y se juntan todos.
 */
window.Escaner = (() => {
  "use strict";
  let cargando = null;
  function cargarZXing() {
    if (window.ZXing) return Promise.resolve(window.ZXing);
    if (!cargando) cargando = new Promise((ok, mal) => {
      const s = document.createElement("script");
      s.src = "/zxing.min.js";
      s.onload = () => window.ZXing ? ok(window.ZXing) : mal(new Error("No se pudo cargar el lector de códigos."));
      s.onerror = () => { cargando = null; mal(new Error("No se pudo cargar el lector de códigos.")); };
      document.head.append(s);
    });
    return cargando;
  }

  function imagenDe(archivo) {
    return new Promise((ok, mal) => {
      const url = URL.createObjectURL(archivo);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); ok(img); };
      img.onerror = () => { URL.revokeObjectURL(url); mal(new Error("No se pudo abrir la foto.")); };
      img.src = url;
    });
  }

  // Canvas con la imagen achicada (las fotos del celular son enormes y ZXing se pone lento) y girada
  function lienzo(img, girar) {
    const MAX = 1600;
    const esc = Math.min(1, MAX / Math.max(img.naturalWidth, img.naturalHeight));
    const w = Math.round(img.naturalWidth * esc), h = Math.round(img.naturalHeight * esc);
    const c = document.createElement("canvas");
    c.width = girar ? h : w; c.height = girar ? w : h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    if (girar) { ctx.translate(h, 0); ctx.rotate(Math.PI / 2); }
    ctx.drawImage(img, 0, 0, w, h);
    return c;
  }

  function recorte(c, y, alto) {
    const r = document.createElement("canvas");
    r.width = c.width; r.height = alto;
    r.getContext("2d", { willReadFrequently: true }).drawImage(c, 0, y, c.width, alto, 0, 0, c.width, alto);
    return r;
  }

  function leerLienzo(Z, lector, c) {
    try {
      const fuente = new Z.HTMLCanvasElementLuminanceSource(c);
      return lector.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(fuente))).getText();
    } catch { return null; }
    finally { lector.reset(); }
  }

  // Devuelve los textos leidos (sin repetir), en el orden en que aparecen de arriba hacia abajo
  async function leerFoto(archivo) {
    const Z = await cargarZXing();
    const img = await imagenDe(archivo);
    const hints = new Map();
    hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.CODE_128, Z.BarcodeFormat.CODE_39, Z.BarcodeFormat.EAN_13,
      Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.ITF, Z.BarcodeFormat.QR_CODE, Z.BarcodeFormat.DATA_MATRIX]);
    hints.set(Z.DecodeHintType.TRY_HARDER, true);
    const lector = new Z.MultiFormatReader();
    lector.setHints(hints);
    const textos = [];
    const sumar = t => { if (t && !textos.includes(t.trim())) textos.push(t.trim()); };
    for (const girar of [false, true]) {
      const c = lienzo(img, girar);
      sumar(leerLienzo(Z, lector, c));
      // Franjas superpuestas: de a 1/4 del alto, avanzando 1/8
      const alto = Math.max(40, Math.round(c.height / 4)), paso = Math.max(20, Math.round(c.height / 8));
      for (let y = 0; y + alto <= c.height; y += paso) sumar(leerLienzo(Z, lector, recorte(c, y, alto)));
      if (textos.length) break;          // si derecha se leyo algo, no hace falta girarla
    }
    return textos;
  }

  return { leerFoto };
})();
