#!/usr/bin/env python3
"""Audio Admin — gestor local de metadatos y carátulas.

No sube audio a ningún servicio: los ficheros se copian a .audio-admin/ y se
procesan localmente con ffmpeg/ffprobe.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from email.parser import BytesParser
from email.policy import HTTP
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / ".audio-admin"
IMPORTS, COVERS, EXPORTS, BACKUPS = (DATA / name for name in ("imports", "covers", "exports", "backups"))
STATE = DATA / "library.json"
ALLOWED_AUDIO = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".aiff", ".aif"}
EDITABLE = {"title", "artist", "album", "album_artist", "genre", "date", "track", "disc", "composer", "comment", "lyrics", "bpm", "copyright", "isrc", "key", "publisher", "grouping"}
TAG_NAMES = {
    "title": "title", "artist": "artist", "album": "album", "album_artist": "album_artist",
    "genre": "genre", "date": "date", "track": "track", "disc": "disc", "composer": "composer",
    "comment": "comment", "lyrics": "lyrics", "bpm": "bpm", "copyright": "copyright", "isrc": "isrc",
    "key": "initialkey", "publisher": "publisher", "grouping": "grouping",
}

def ensure_data():
    for folder in (IMPORTS, COVERS, EXPORTS, BACKUPS): folder.mkdir(parents=True, exist_ok=True)
    if not STATE.exists(): STATE.write_text(json.dumps({"tracks": {}}, indent=2), encoding="utf-8")

def load_state():
    ensure_data()
    return json.loads(STATE.read_text(encoding="utf-8"))

def save_state(state):
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)

def seconds(value):
    try: return round(float(value), 1)
    except (TypeError, ValueError): return None

def ffprobe(path):
    p = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if p.returncode: raise RuntimeError(p.stderr.strip() or "ffprobe no pudo leer el archivo")
    info = json.loads(p.stdout)
    tags = {str(k).lower(): str(v) for k, v in info.get("format", {}).get("tags", {}).items()}
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    cover = next((s for s in info.get("streams", []) if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic")), None)
    return {"tags": tags, "duration": seconds(info.get("format", {}).get("duration")), "size": int(info.get("format", {}).get("size", 0)), "bitrate": int(info.get("format", {}).get("bit_rate", 0) or 0), "codec": audio.get("codec_name", "—"), "sample_rate": audio.get("sample_rate"), "channels": audio.get("channels"), "cover_embedded": bool(cover), "raw_tags": tags}

def field(tags, *names):
    for name in names:
        if tags.get(name): return tags[name]
    return ""

def public_track(track):
    source = Path(track["source"])
    details = ffprobe(source)
    tags = details.pop("tags")
    edited = track.get("changes", {})
    meta = {
        "title": field(tags, "title") or track["filename"].rsplit(".", 1)[0], "artist": field(tags, "artist"), "album": field(tags, "album"),
        "album_artist": field(tags, "album_artist", "albumartist"), "genre": field(tags, "genre"), "date": field(tags, "date", "year"),
        "track": field(tags, "track", "tracknumber"), "disc": field(tags, "disc", "discnumber"), "composer": field(tags, "composer"),
        "comment": field(tags, "comment", "description"), "lyrics": field(tags, "lyrics", "unsyncedlyrics"), "bpm": field(tags, "bpm", "tbpm"), "copyright": field(tags, "copyright"),
        "isrc": field(tags, "isrc"), "key": field(tags, "initialkey", "key"), "publisher": field(tags, "publisher", "organization"), "grouping": field(tags, "grouping"),
    }
    meta.update({k: v for k, v in edited.items() if k in EDITABLE})
    return {"id": track["id"], "filename": track["filename"], "extension": source.suffix.lower(), "meta": meta, "cover": track.get("cover"), "details": details, "origin": track.get("origin", str(source)), "modified": bool(track.get("changes") or track.get("cover"))}

def add_paths(paths, state):
    """Adds real Mac paths without copying or losing their relationship to Finder."""
    added, known = [], {item.get("origin", item["source"]) for item in state["tracks"].values()}
    for item in paths:
        source = Path(item).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in ALLOWED_AUDIO or str(source) in known: continue
        ident = uuid.uuid4().hex
        state["tracks"][ident] = {"id": ident, "filename": source.name, "source": str(source), "origin": str(source), "changes": {}}
        added.append(ident); known.add(str(source))
    return added

def choose_with_finder(kind):
    if kind == "folder":
        script = 'POSIX path of (choose folder with prompt "Selecciona la carpeta de música")'
        picked = run(["osascript", "-e", script])
        if picked.returncode: return []
        return [str(p) for p in Path(picked.stdout.strip()).rglob("*") if p.suffix.lower() in ALLOWED_AUDIO]
    script = 'set fs to choose file with prompt "Selecciona archivos de audio" with multiple selections allowed\nset out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out'
    picked = run(["osascript", "-e", script])
    if picked.returncode: return []
    return [line for line in picked.stdout.splitlines() if line]

def embedded_cover(source, output):
    result = run(["ffmpeg", "-y", "-i", str(source), "-an", "-map", "0:v:0", "-frames:v", "1", "-update", "1", str(output)])
    return result.returncode == 0 and output.is_file()

def safe_name(name):
    return re.sub(r"[^\w .()\-]", "_", name, flags=re.UNICODE).strip() or "audio"

def optimize_cover(upload, name):
    base = COVERS / f"{uuid.uuid4().hex}.jpg"
    raw = COVERS / f"raw-{uuid.uuid4().hex}{Path(name).suffix.lower() or '.img'}"
    raw.write_bytes(upload)
    process = run(["ffmpeg", "-y", "-i", str(raw), "-vf", "scale=1400:1400:force_original_aspect_ratio=decrease,pad=1400:1400:(ow-iw)/2:(oh-ih)/2:color=white", "-frames:v", "1", "-q:v", "3", str(base)])
    raw.unlink(missing_ok=True)
    if process.returncode:
        base.unlink(missing_ok=True)
        raise RuntimeError("No se pudo procesar la imagen: " + process.stderr[-400:])
    return str(base.relative_to(DATA))

def export_track(track, output_dir):
    source = Path(track["source"])
    item = public_track(track)
    # The staging copy has a UUID name; exports retain the user-facing filename.
    output = output_dir / safe_name(track["filename"])
    cmd = ["ffmpeg", "-y", "-i", str(source)]
    cover = track.get("cover")
    if cover:
        cmd += ["-i", str(DATA / cover), "-map", "0:a:0", "-map", "1:v:0", "-c:a", "copy", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
    else:
        # Preserve every original stream and its metadata, including attached artwork.
        cmd += ["-map", "0", "-map_metadata", "0", "-c", "copy"]
    for key, value in item["meta"].items():
        if value:
            cmd += ["-metadata", f"{TAG_NAMES[key]}={value}"]
    if source.suffix.lower() in {".m4a", ".mp4", ".aac"}: cmd += ["-movflags", "use_metadata_tags"]
    cmd += [str(output)]
    result = run(cmd)
    if result.returncode:
        raise RuntimeError(f"{source.name}: " + result.stderr[-600:])
    return output

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT / "web"), **kwargs)
    def log_message(self, *_): pass
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", len(body)); self.end_headers(); self.wfile.write(body)
    def local_request(self):
        """Solo acepta esta misma página: otra web abierta en el navegador no puede usar la API."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return host.split(":")[0] in {"127.0.0.1", "localhost"} and origin in {None, f"http://{host}"}
    def read_files(self, field):
        # shortcut: el envío completo se lee en memoria; pasar a ficheros temporales si se suben lotes de varios GB.
        head = f"Content-Type: {self.headers.get('Content-Type', '')}\r\n\r\n".encode()
        form = BytesParser(policy=HTTP).parsebytes(head + self.rfile.read(int(self.headers.get("Content-Length", 0))))
        parts = form.iter_parts() if form.is_multipart() else []
        return [(p.get_filename(), p.get_payload(decode=True)) for p in parts if p.get_param("name", header="content-disposition") == field and p.get_filename()]
    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
    def do_GET(self):
        if not self.local_request(): return self.send_json({"error": "Origen no permitido"}, 403)
        parsed = urlparse(self.path)
        if parsed.path == "/api/tracks":
            state = load_state(); tracks = []
            for t in state["tracks"].values():
                try: tracks.append(public_track(t))
                except Exception: pass
            return self.send_json({"tracks": tracks})
        if parsed.path.startswith("/api/track-cover/"):
            ident = Path(parsed.path).name; track = load_state()["tracks"].get(ident)
            if track:
                cover = track.get("cover")
                picture = DATA / cover if cover else COVERS / f"embedded-{ident}.jpg"
                if (cover and picture.is_file()) or (not cover and embedded_cover(Path(track["source"]), picture)):
                    self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", picture.stat().st_size); self.end_headers(); return self.wfile.write(picture.read_bytes())
        if parsed.path.startswith("/api/cover/"):
            path = DATA / "covers" / Path(parsed.path).name
            if path.is_file():
                self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", path.stat().st_size); self.end_headers(); return self.wfile.write(path.read_bytes())
        if parsed.path.startswith("/api/download/"):
            path = EXPORTS / Path(parsed.path).name
            if path.is_file():
                self.send_response(200); self.send_header("Content-Type", "application/zip"); self.send_header("Content-Disposition", f'attachment; filename="{path.name}"'); self.send_header("Content-Length", path.stat().st_size); self.end_headers(); return self.wfile.write(path.read_bytes())
        return super().do_GET()
    def do_POST(self):
        if not self.local_request(): return self.send_json({"error": "Origen no permitido"}, 403)
        path = urlparse(self.path).path
        try:
            if path in {"/api/import", "/api/cover"}:
                if path == "/api/import":
                    state, added = load_state(), []
                    for name, data in self.read_files("files"):
                        if Path(name).suffix.lower() not in ALLOWED_AUDIO: continue
                        ident = uuid.uuid4().hex; filename = safe_name(Path(name).name); dest = IMPORTS / f"{ident}{Path(filename).suffix.lower()}"
                        dest.write_bytes(data)
                        state["tracks"][ident] = {"id": ident, "filename": filename, "source": str(dest), "origin": str(dest), "managed_copy": True, "changes": {}}; added.append(ident)
                    save_state(state); return self.send_json({"added": added})
                uploads = self.read_files("cover")
                if not uploads: raise ValueError("Selecciona una imagen.")
                name, data = uploads[0]
                return self.send_json({"cover": Path(optimize_cover(data, name)).name})
            payload, state = self.read_json(), load_state()
            ids = [x for x in payload.get("ids", []) if x in state["tracks"]]
            if path in {"/api/pick-files", "/api/pick-folder"}:
                added = add_paths(choose_with_finder("folder" if path.endswith("folder") else "files"), state)
                save_state(state); return self.send_json({"added": added})
            if path == "/api/edit":
                changes = {k: str(v).strip() for k, v in payload.get("changes", {}).items() if k in EDITABLE}
                for ident in ids: state["tracks"][ident]["changes"].update(changes)
                save_state(state); return self.send_json({"ok": True})
            if path == "/api/assign-cover":
                cover = payload.get("cover", "")
                if not (COVERS / Path(cover).name).is_file(): raise ValueError("Carátula no encontrada.")
                for ident in ids: state["tracks"][ident]["cover"] = f"covers/{Path(cover).name}"
                save_state(state); return self.send_json({"ok": True})
            if path == "/api/remove":
                for ident in ids:
                    entry = state["tracks"].pop(ident, None)
                    if entry and entry.get("managed_copy"): Path(entry["source"]).unlink(missing_ok=True)
                save_state(state); return self.send_json({"ok": True})
            if path == "/api/export":
                if not ids: raise ValueError("Selecciona al menos un archivo.")
                stamp = time.strftime("%Y%m%d-%H%M%S"); target = EXPORTS / f"Audio-Admin-{stamp}"; target.mkdir(parents=True)
                produced = [export_track(state["tracks"][ident], target) for ident in ids]
                archive = EXPORTS / f"Audio-Admin-{stamp}.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                    for file in produced: z.write(file, file.name)
                shutil.rmtree(target)
                return self.send_json({"download": archive.name, "count": len(produced)})
            if path == "/api/save-originals":
                if not ids: raise ValueError("Selecciona al menos un archivo.")
                stamp = time.strftime("%Y%m%d-%H%M%S"); target = EXPORTS / f"save-{stamp}"; target.mkdir(parents=True); backup = BACKUPS / stamp; backup.mkdir(parents=True)
                saved = 0
                for ident in ids:
                    track = state["tracks"][ident]; source = Path(track["source"]); made = export_track(track, target)
                    shutil.copy2(source, backup / source.name); shutil.copy2(made, source); track["changes"] = {}; track.pop("cover", None); saved += 1
                save_state(state); shutil.rmtree(target)
                return self.send_json({"ok": True, "count": saved, "backup": str(backup)})
            self.send_json({"error": "Ruta no encontrada"}, 404)
        except (ValueError, RuntimeError) as error: self.send_json({"error": str(error)}, 400)
        except Exception as error: self.send_json({"error": "Error inesperado: " + str(error)}, 500)

def main():
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing: raise SystemExit("Falta " + " y ".join(missing) + ". Instálalo con: brew install ffmpeg")
    ensure_data()
    port = int(os.environ.get("AUDIO_ADMIN_PORT", "8060"))
    print(f"Audio Admin listo en http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

if __name__ == "__main__": main()
