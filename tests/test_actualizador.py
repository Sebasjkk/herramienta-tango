"""Pruebas del actualizador automatico, sin conectarse a GitHub."""

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from herramienta_tango.actualizador import Actualizador, es_mas_nueva, version_a_tupla


def armar_zip(archivos: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return buffer.getvalue()


PAQUETE_BUENO = armar_zip({
    "HerramientaTango.pyw": "# v1.5",
    "herramienta_tango/__init__.py": 'VERSION = "1.5"',
})
SHA_BUENO = hashlib.sha256(PAQUETE_BUENO).hexdigest()


def release(version="v1.5", con_sha=True):
    activos = [{"name": "HerramientaTango-app.zip", "browser_download_url": "https://x/zip"}]
    if con_sha:
        activos.append({"name": "HerramientaTango-app.zip.sha256", "browser_download_url": "https://x/sha"})
    return {"tag_name": version, "assets": activos}


class TestVersiones(unittest.TestCase):
    def test_parseo(self):
        self.assertEqual(version_a_tupla("v1.12"), (1, 12))
        self.assertEqual(version_a_tupla("1.2"), (1, 2))
        self.assertIsNone(version_a_tupla("0.0-dev"))

    def test_comparacion_numerica(self):
        self.assertTrue(es_mas_nueva("1.10", "1.9"))   # 10 > 9, no comparacion de texto
        self.assertFalse(es_mas_nueva("1.9", "1.10"))
        self.assertFalse(es_mas_nueva("1.5", "1.5"))
        self.assertFalse(es_mas_nueva("1.5", "0.0-dev"))  # en desarrollo no se actualiza


class TestInstalacion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        app = self.raiz / "app"
        (app / "herramienta_tango").mkdir(parents=True)
        (app / "HerramientaTango.pyw").write_text("# v1.4")
        self.reinicios = []

    def tearDown(self):
        self.tmp.cleanup()

    def crear(self, datos_release=None, paquete=PAQUETE_BUENO, sha=SHA_BUENO, version="1.4",
              automatica=True, raiz="usar"):
        return Actualizador(
            version, "dueno/repo", 15, automatica,
            al_instalar=lambda: self.reinicios.append(True),
            raiz=self.raiz if raiz == "usar" else raiz,
            obtener_json=lambda url: datos_release or release(),
            descargar=lambda url, destino: destino.write_bytes(paquete),
            obtener_texto=lambda url: f"{sha}  HerramientaTango-app.zip",
        )

    def entrada(self) -> str:
        return (self.raiz / "app" / "HerramientaTango.pyw").read_text()

    def test_instala_version_nueva(self):
        a = self.crear()
        a.revisar()
        self.assertEqual(a.estado.estado, "reiniciando", a.estado.mensaje)
        self.assertEqual(self.entrada(), "# v1.5")
        self.assertEqual((self.raiz / "app.old" / "HerramientaTango.pyw").read_text(), "# v1.4")
        self.assertFalse((self.raiz / "app.new").exists())
        self.assertFalse((self.raiz / "app.new.zip").exists())
        self.assertEqual(self.reinicios, [True])

    def test_sha_distinto_no_instala(self):
        a = self.crear(paquete=b"archivo corrupto")
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertEqual(self.entrada(), "# v1.4")
        self.assertFalse((self.raiz / "app.new.zip").exists())
        self.assertEqual(self.reinicios, [])

    def test_paquete_incompleto_no_instala(self):
        incompleto = armar_zip({"LEEME.txt": "nada"})
        a = self.crear(paquete=incompleto, sha=hashlib.sha256(incompleto).hexdigest())
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertIn("incompleto", a.estado.mensaje)
        self.assertEqual(self.entrada(), "# v1.4")
        self.assertFalse((self.raiz / "app.new").exists())

    def test_zip_con_rutas_peligrosas_no_instala(self):
        malicioso = armar_zip({"../fuera.txt": "x", "HerramientaTango.pyw": "x", "herramienta_tango/a.py": ""})
        a = self.crear(paquete=malicioso, sha=hashlib.sha256(malicioso).hexdigest())
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertFalse((self.raiz / "fuera.txt").exists())
        self.assertEqual(self.entrada(), "# v1.4")

    def test_sin_archivo_sha_no_instala(self):
        a = self.crear(datos_release=release(con_sha=False))
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertEqual(self.entrada(), "# v1.4")

    def test_al_dia(self):
        a = self.crear(datos_release=release("v1.4"))
        a.revisar()
        self.assertEqual(a.estado.estado, "al_dia")
        self.assertEqual(self.reinicios, [])

    def test_manual_solo_avisa(self):
        a = self.crear(automatica=False)
        a.revisar()
        self.assertEqual(a.estado.estado, "disponible")
        self.assertEqual(a.estado.version_disponible, "1.5")
        self.assertEqual(self.entrada(), "# v1.4")

    def test_pedido_a_mano_instala_aunque_no_sea_automatica(self):
        a = self.crear(automatica=False)
        a.revisar(instalar=True)
        self.assertEqual(a.estado.estado, "reiniciando")
        self.assertEqual(self.entrada(), "# v1.5")

    def test_desde_codigo_fuente_no_instala(self):
        a = self.crear(raiz=None)
        a.revisar()
        self.assertEqual(a.estado.estado, "disponible")
        self.assertEqual(self.entrada(), "# v1.4")

    def test_github_caido(self):
        def falla(url):
            raise OSError("sin internet")
        a = self.crear()
        a._obtener_json = falla
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertEqual(self.entrada(), "# v1.4")

    def test_limpia_restos(self):
        a = self.crear()
        (self.raiz / "app.old" / "x").mkdir(parents=True)
        (self.raiz / "app.new.zip").write_bytes(b"resto")
        a.limpiar_restos()
        self.assertFalse((self.raiz / "app.old").exists())
        self.assertFalse((self.raiz / "app.new.zip").exists())
        self.assertTrue((self.raiz / "app").exists())


if __name__ == "__main__":
    unittest.main()
