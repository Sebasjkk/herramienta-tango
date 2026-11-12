"""Pruebas del actualizador automatico, sin conectarse a GitHub."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from herramienta_tango.actualizador import Actualizador, es_mas_nueva, version_a_tupla

EXE_NUEVO = b"exe nuevo v1.5"
SHA_NUEVO = hashlib.sha256(EXE_NUEVO).hexdigest()


def release(version="v1.5", con_sha=True):
    activos = [{"name": "HerramientaTango.exe", "browser_download_url": "https://x/exe"}]
    if con_sha:
        activos.append({"name": "HerramientaTango.exe.sha256", "browser_download_url": "https://x/sha"})
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
        self.exe = Path(self.tmp.name) / "HerramientaTango.exe"
        self.exe.write_bytes(b"exe viejo v1.4")
        self.instalado = []

    def tearDown(self):
        self.tmp.cleanup()

    def crear(self, datos_release=None, contenido=EXE_NUEVO, sha=SHA_NUEVO, version="1.4", automatica=True):
        return Actualizador(
            version, "dueno/repo", 15, automatica,
            al_instalar=self.instalado.append,
            ruta_exe=self.exe,
            obtener_json=lambda url: datos_release or release(),
            descargar=lambda url, destino: destino.write_bytes(contenido),
            obtener_texto=lambda url: f"{sha}  HerramientaTango.exe",
        )

    def test_instala_version_nueva(self):
        a = self.crear()
        a.revisar()
        self.assertEqual(a.estado.estado, "reiniciando")
        self.assertEqual(self.exe.read_bytes(), EXE_NUEVO)
        self.assertEqual(a.ruta_vieja.read_bytes(), b"exe viejo v1.4")
        self.assertFalse(a.ruta_nueva.exists())
        self.assertEqual(self.instalado, [self.exe])

    def test_sha_distinto_no_instala(self):
        a = self.crear(contenido=b"archivo corrupto")
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertEqual(self.exe.read_bytes(), b"exe viejo v1.4")
        self.assertFalse(a.ruta_nueva.exists())
        self.assertEqual(self.instalado, [])

    def test_sin_archivo_sha_no_instala(self):
        a = self.crear(datos_release=release(con_sha=False))
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertEqual(self.exe.read_bytes(), b"exe viejo v1.4")

    def test_al_dia(self):
        a = self.crear(datos_release=release("v1.4"))
        a.revisar()
        self.assertEqual(a.estado.estado, "al_dia")
        self.assertEqual(self.instalado, [])

    def test_manual_solo_avisa(self):
        a = self.crear(automatica=False)
        a.revisar()
        self.assertEqual(a.estado.estado, "disponible")
        self.assertEqual(a.estado.version_disponible, "1.5")
        self.assertEqual(self.exe.read_bytes(), b"exe viejo v1.4")

    def test_github_caido(self):
        def falla(url):
            raise OSError("sin internet")
        a = self.crear()
        a._obtener_json = falla
        a.revisar()
        self.assertEqual(a.estado.estado, "error")
        self.assertEqual(self.exe.read_bytes(), b"exe viejo v1.4")

    def test_limpia_restos(self):
        a = self.crear()
        a.ruta_vieja.write_bytes(b"resto")
        a.limpiar_restos()
        self.assertFalse(a.ruta_vieja.exists())


if __name__ == "__main__":
    unittest.main()
