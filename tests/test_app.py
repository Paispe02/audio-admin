"""Importa un tono, cambia el título, exporta y comprueba la etiqueta. Uso: python3 tests/test_app.py"""
import io, json, subprocess, sys, tempfile, threading, urllib.error, urllib.request, zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

tmp = Path(tempfile.mkdtemp())
app.DATA = tmp / "datos"
app.IMPORTS, app.COVERS, app.EXPORTS, app.BACKUPS = (app.DATA / n for n in ("imports", "covers", "exports", "backups"))
app.STATE = app.DATA / "library.json"
app.ensure_data()
server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"

def call(path, data=None, kind="application/json", **headers):
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    return urllib.request.urlopen(urllib.request.Request(base + path, body, {"Content-Type": kind, **headers})).read()

def upload(path, field, file):
    body = (f'--x\r\nContent-Disposition: form-data; name="{field}"; filename="{file.name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + file.read_bytes() + b"\r\n--x--\r\n"
    return json.loads(call(path, body, "multipart/form-data; boundary=x"))

tone, image = tmp / "tono de prueba.mp3", tmp / "portada.png"
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(tone)], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1", str(image)], check=True)

ids = upload("/api/import", "files", tone)["added"]
assert len(ids) == 1
assert (app.IMPORTS / f"{ids[0]}.mp3").read_bytes() == tone.read_bytes(), "el audio importado debe ser idéntico"
call("/api/edit", {"ids": ids, "changes": {"title": "Título nuevo", "artist": "Artista"}})
cover = upload("/api/cover", "cover", image)["cover"]
call("/api/assign-cover", {"ids": ids, "cover": cover})
name = json.loads(call("/api/export", {"ids": ids}))["download"]
with zipfile.ZipFile(io.BytesIO(call(f"/api/download/{name}"))) as z:
    z.extractall(tmp / "salida")
info = app.ffprobe(tmp / "salida" / "tono de prueba.mp3")
assert info["tags"]["title"] == "Título nuevo" and info["cover_embedded"]
for headers in ({"Origin": "https://otra-web.example"}, {"Host": "otra-web.example"}):
    try:
        call("/api/tracks", **headers)
        raise AssertionError("debería rechazar otro origen")
    except urllib.error.HTTPError as error:
        assert error.code == 403
print("OK")
