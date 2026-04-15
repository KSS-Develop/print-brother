"""
Vercel Function: PDF → HBP (Brother Host Based Printing)
========================================================

Recibe un PDF en POST body, lo convierte a HBP (formato propietario Brother)
usando GhostScript + brlaser, y devuelve el HBP raw para enviar al puerto 9100
de la impresora Brother DCP-1610NW.

Pipeline:
    PDF (POST body)
      → GhostScript (gs -sDEVICE=cups -r300 -o /tmp/x.cupsraster)
      → brlaser (rastertobrlaser 1 user title 1 "" /tmp/x.cupsraster)
      → HBP binary (response body)

El cliente (iOS Shortcut) recibe el HBP y lo manda al puerto 9100 de la Brother
en la red local.
"""

import os
import sys
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler

# Path donde Vercel monta los binarios incluidos en el repo
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BIN_DIR = os.path.join(ROOT, "bin")
LIB_DIR = os.path.join(ROOT, "lib")
GS_SHARE = os.path.join(ROOT, "gs_share")
PPD_PATH = os.path.join(ROOT, "ppd", "br1600.ppd")
GS_BIN = os.path.join(BIN_DIR, "gs")
BRLASER_BIN = os.path.join(BIN_DIR, "rastertobrlaser")

# Variables CUPS que brlaser espera en el environment + LD_LIBRARY_PATH
# para shared libs + GS_LIB para los .ps de inicialización de GhostScript
# + PPD con path al .ppd de brlaser para DCP-1600 series (el modelo de nuestra Brother)
CUPS_ENV = {
    "PPD": PPD_PATH,
    "CONTENT_TYPE": "application/vnd.cups-raster",
    "DEVICE_URI": "socket://localhost:9100",
    "PRINTER": "Brother",
    "USER": "vercel",
    "LANG": "C",
    "LD_LIBRARY_PATH": LIB_DIR + ":" + os.environ.get("LD_LIBRARY_PATH", ""),
    "GS_LIB": (
        f"{GS_SHARE}/Resource/Init:"
        f"{GS_SHARE}/lib:"
        f"{GS_SHARE}/Resource:"
        f"{GS_SHARE}/Resource/Font:"
        f"{GS_SHARE}/iccprofiles"
    ),
}


def convert_pdf_to_hbp(pdf_bytes: bytes) -> bytes:
    """Pipeline PDF → CUPS Raster → HBP."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "in.pdf")
        raster_path = os.path.join(tmp, "out.cupsraster")
        hbp_path = os.path.join(tmp, "out.hbp")

        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        # Step 1: PDF → CUPS raster (1-bit B/W, 600 DPI)
        # DCP-1600 series solo soporta 600 y 1200 DPI (no 300)
        # Papel: letter (puede ser A4, pero letter funciona OK por defecto)
        gs_cmd = [
            GS_BIN,
            "-dQUIET",
            "-dBATCH",
            "-dNOPAUSE",
            "-dSAFER",
            "-sDEVICE=cups",
            "-r600x600",
            "-sPAPERSIZE=letter",
            "-dcupsBitsPerColor=1",
            "-dcupsColorOrder=0",
            "-dcupsColorSpace=3",  # K (black)
            "-dcupsNumColors=1",
            f"-sOutputFile={raster_path}",
            pdf_path,
        ]
        gs_result = subprocess.run(gs_cmd, capture_output=True, env={**os.environ, **CUPS_ENV})
        if gs_result.returncode != 0:
            raise RuntimeError(f"gs failed ({gs_result.returncode}): {gs_result.stderr.decode()[:500]}")

        # Step 2: CUPS raster → HBP via brlaser
        with open(raster_path, "rb") as raster_in, open(hbp_path, "wb") as hbp_out:
            br_result = subprocess.run(
                [BRLASER_BIN, "1", "vercel", "print", "1", ""],
                stdin=raster_in,
                stdout=hbp_out,
                stderr=subprocess.PIPE,
                env={**os.environ, **CUPS_ENV},
            )
        if br_result.returncode != 0:
            raise RuntimeError(f"brlaser failed ({br_result.returncode}): {br_result.stderr.decode()[:500]}")

        with open(hbp_path, "rb") as f:
            return f.read()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_headers_common("text/plain")
        self.end_headers()
        self.wfile.write(b"print-brother converter is alive\nPOST a PDF body to /api/convert\n")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_headers_common("text/plain")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 20 * 1024 * 1024:  # 20 MB max
                self.send_error_json(400, "PDF body required (max 20 MB)")
                return

            pdf_bytes = self.rfile.read(length)
            if pdf_bytes[:4] != b"%PDF":
                self.send_error_json(400, "Body is not a PDF (missing %PDF header)")
                return

            hbp = convert_pdf_to_hbp(pdf_bytes)

            self.send_response(200)
            self.send_headers_common("application/octet-stream")
            self.send_header("Content-Length", str(len(hbp)))
            self.send_header("X-Brother-Format", "HBP")
            self.end_headers()
            self.wfile.write(hbp)
        except Exception as exc:
            self.send_error_json(500, f"conversion failed: {exc}")

    def send_headers_common(self, content_type: str):
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_error_json(self, code: int, message: str):
        body = f'{{"error":{message!r}}}'.encode()
        self.send_response(code)
        self.send_headers_common("application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
