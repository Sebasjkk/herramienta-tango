"""
GitHub falso para probar la actualizacion automatica del .exe en el workflow.

La primera consulta de "ultima version" anuncia la v99.0 (siempre mas nueva);
las siguientes anuncian la v0.1, para que el programa reiniciado quede al dia
y no entre en un ciclo de actualizaciones. Registra lo que le piden en un log.

Uso: python servidor_releases_falso.py RUTA_EXE PUERTO RUTA_LOG
"""

import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

exe = Path(sys.argv[1]).read_bytes()
puerto = int(sys.argv[2])
log = Path(sys.argv[3])
sha = hashlib.sha256(exe).hexdigest()
consultas = {"n": 0}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _enviar(self, cuerpo: bytes, tipo="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        with open(log, "a", encoding="utf-8") as f:
            f.write(self.path + "\n")
        base = f"http://127.0.0.1:{puerto}"
        if self.path == "/releases/latest":
            consultas["n"] += 1
            version = "v99.0" if consultas["n"] == 1 else "v0.1"
            datos = {"tag_name": version, "assets": [
                {"name": "HerramientaTango.exe", "browser_download_url": base + "/exe"},
                {"name": "HerramientaTango.exe.sha256", "browser_download_url": base + "/sha"},
            ]}
            self._enviar(json.dumps(datos).encode(), "application/json")
        elif self.path == "/exe":
            self._enviar(exe)
        elif self.path == "/sha":
            self._enviar(f"{sha}  HerramientaTango.exe".encode())
        else:
            self.send_response(404)
            self.end_headers()


ThreadingHTTPServer(("127.0.0.1", puerto), H).serve_forever()
