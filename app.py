import os
import time
import socket
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask, request, session, redirect, render_template,
    jsonify, send_from_directory, abort, url_for, flash
)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
UP = os.path.join(DATA, "uploads")
os.makedirs(UP, exist_ok=True)
DB = os.path.join(DATA, "painel.db")
DEFAULT_PASSWORD = os.environ.get("ADMIN_PASSWORD", "trocar123")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "painel-led-secret-key-shop-cor-2026")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB max upload

VIDEO = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}
IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS media(
            id INTEGER PRIMARY KEY,
            name TEXT,
            kind TEXT,
            file TEXT,
            duration INTEGER DEFAULT 10,
            client_name TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS screens(
            id INTEGER PRIMARY KEY,
            name TEXT,
            slug TEXT UNIQUE,
            seen REAL DEFAULT 0,
            fit_mode TEXT DEFAULT 'cover',
            rotation INTEGER DEFAULT 0,
            muted INTEGER DEFAULT 1,
            transition TEXT DEFAULT 'fade',
            resolution TEXT DEFAULT '1920x1080',
            current_media TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY,
            screen_id INTEGER,
            media_id INTEGER,
            pos INTEGER,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        # Safe migrations for existing databases
        media_cols = {r["name"] for r in c.execute("PRAGMA table_info(media)").fetchall()}
        migrations_media = [
            ("client_name", "TEXT DEFAULT ''"),
            ("active", "INTEGER DEFAULT 1"),
            ("start_date", "TEXT DEFAULT ''"),
            ("end_date", "TEXT DEFAULT ''"),
            ("start_time", "TEXT DEFAULT ''"),
            ("end_time", "TEXT DEFAULT ''"),
            ("file_size", "INTEGER DEFAULT 0"),
            ("created_at", "REAL DEFAULT 0"),
        ]
        for col, col_def in migrations_media:
            if col not in media_cols:
                c.execute(f"ALTER TABLE media ADD COLUMN {col} {col_def}")

        screen_cols = {r["name"] for r in c.execute("PRAGMA table_info(screens)").fetchall()}
        migrations_screens = [
            ("fit_mode", "TEXT DEFAULT 'cover'"),
            ("rotation", "INTEGER DEFAULT 0"),
            ("muted", "INTEGER DEFAULT 1"),
            ("transition", "TEXT DEFAULT 'fade'"),
            ("resolution", "TEXT DEFAULT '1920x1080'"),
            ("current_media", "TEXT DEFAULT ''"),
        ]
        for col, col_def in migrations_screens:
            if col not in screen_cols:
                c.execute(f"ALTER TABLE screens ADD COLUMN {col} {col_def}")

        item_cols = {r["name"] for r in c.execute("PRAGMA table_info(items)").fetchall()}
        if "active" not in item_cols:
            c.execute("ALTER TABLE items ADD COLUMN active INTEGER DEFAULT 1")

        # Create default screen if none exists
        count_screens = c.execute("SELECT COUNT(*) FROM screens").fetchone()[0]
        if count_screens == 0:
            c.execute(
                "INSERT INTO screens(name, slug, fit_mode, rotation, muted, transition, resolution) VALUES(?,?,?,?,?,?,?)",
                ("Painel LED Principal", "painel-principal", "cover", 0, 1, "fade", "1920x1080")
            )


init_db()


def get_setting(key, default=""):
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key, value):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, str(value)))


def verify_password(password_input):
    stored_hash = get_setting("admin_password_hash", "")
    if stored_hash:
        return check_password_hash(stored_hash, password_input)
    return password_input == DEFAULT_PASSWORD


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_media_schedule_status(m):
    """Returns ('active', 'Ativa'), ('paused', 'Pausada'), ('expired', 'Vencida'), ('scheduled', 'Agendada'), or ('off_hours', 'Fora do horário')"""
    if not m["active"]:
        return "paused", "Pausada"

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    start_date = (m["start_date"] or "").strip()
    end_date = (m["end_date"] or "").strip()
    start_time = (m["start_time"] or "").strip()
    end_time = (m["end_time"] or "").strip()

    if start_date and today_str < start_date:
        return "scheduled", f"Inicia em {start_date[8:10]}/{start_date[5:7]}"
    if end_date and today_str > end_date:
        return "expired", f"Venceu em {end_date[8:10]}/{end_date[5:7]}"

    if start_time and end_time:
        if start_time <= end_time:
            if not (start_time <= time_str <= end_time):
                return "off_hours", f"Horário: {start_time} às {end_time}"
        else:
            # Overnight schedule (e.g. 20:00 to 06:00)
            if not (time_str >= start_time or time_str <= end_time):
                return "off_hours", f"Horário: {start_time} às {end_time}"
    elif start_time and time_str < start_time:
        return "off_hours", f"A partir das {start_time}"
    elif end_time and time_str > end_time:
        return "off_hours", f"Até as {end_time}"

    return "active", "Em exibição"


def format_size(num_bytes):
    if not num_bytes:
        return "0 KB"
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit in ("MB", "GB") else f"{int(num_bytes)} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def auth(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("ok"):
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"error": "Não autorizado"}), 401
            return redirect("/login")
        return f(*a, **k)
    return w


@app.route("/login", methods=["GET", "POST"])
def login():
    err = False
    brand_name = get_setting("brand_name", "Shop Cor Tintas")
    if request.method == "POST":
        if verify_password(request.form.get("senha", "")):
            session["ok"] = True
            return redirect("/")
        err = True
    return render_template("login.html", err=err, brand_name=brand_name)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
@auth
def admin():
    c = db()
    raw_media = c.execute("SELECT * FROM media ORDER BY id DESC").fetchall()
    media = []
    total_bytes = 0
    active_media_count = 0
    expired_media_count = 0

    for m in raw_media:
        md = dict(m)
        fsize = md.get("file_size") or 0
        if not fsize:
            fpath = os.path.join(UP, md["file"])
            if os.path.exists(fpath):
                fsize = os.path.getsize(fpath)
        total_bytes += fsize
        md["size_human"] = format_size(fsize)
        st_code, st_label = get_media_schedule_status(md)
        md["status_code"] = st_code
        md["status_label"] = st_label
        if st_code == "active":
            active_media_count += 1
        elif st_code == "expired":
            expired_media_count += 1
        media.append(md)

    screens = []
    online_screens_count = 0
    for s in c.execute("SELECT * FROM screens ORDER BY id").fetchall():
        pl_rows = c.execute("""
            SELECT i.id, i.active as item_active, i.media_id,
                   m.name, m.kind, m.file, m.duration, m.client_name,
                   m.active, m.start_date, m.end_date, m.start_time, m.end_time
            FROM items i
            JOIN media m ON m.id = i.media_id
            WHERE i.screen_id = ?
            ORDER BY i.pos, i.id
        """, (s["id"],)).fetchall()

        pl = []
        total_duration = 0
        playable_count = 0
        for row in pl_rows:
            rd = dict(row)
            st_code, st_label = get_media_schedule_status(rd)
            if not rd["item_active"]:
                st_code = "paused"
                st_label = "Pausado na tela"
            rd["status_code"] = st_code
            rd["status_label"] = st_label
            if st_code == "active":
                playable_count += 1
                total_duration += int(rd["duration"] or 10)
            pl.append(rd)

        is_online = (time.time() - (s["seen"] or 0)) < 90
        if is_online:
            online_screens_count += 1

        last_seen_str = "Nunca conectado"
        if s["seen"] and s["seen"] > 0:
            diff = int(time.time() - s["seen"])
            if diff < 60:
                last_seen_str = f"há {diff}s"
            elif diff < 3600:
                last_seen_str = f"há {diff // 60} min"
            elif diff < 86400:
                last_seen_str = f"há {diff // 3600}h"
            else:
                last_seen_str = datetime.fromtimestamp(s["seen"]).strftime("%d/%m %H:%M")

        screens.append(dict(
            s,
            pl=pl,
            online=is_online,
            last_seen_str=last_seen_str,
            total_duration=total_duration,
            playable_count=playable_count
        ))

    local_ip = get_local_ip()
    port = request.host.split(":")[-1] if ":" in request.host else "5000"
    if "localhost" in request.host or "127.0.0.1" in request.host:
        network_base = f"http://{local_ip}:{port}/"
    else:
        network_base = request.host_url

    stats = {
        "total_media": len(media),
        "active_media": active_media_count,
        "expired_media": expired_media_count,
        "total_size": format_size(total_bytes),
        "total_screens": len(screens),
        "online_screens": online_screens_count,
    }
    brand_name = get_setting("brand_name", "Shop Cor Tintas")

    return render_template(
        "admin.html",
        media=media,
        screens=screens,
        base=request.host_url,
        network_base=network_base,
        local_ip=local_ip,
        stats=stats,
        brand_name=brand_name
    )


@app.post("/media")
@auth
def upload():
    files = request.files.getlist("file")
    if not files or all(not f.filename for f in files):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": "Nenhum arquivo enviado."}), 400
        return redirect("/")

    custom_name = (request.form.get("name") or "").strip()
    client_name = (request.form.get("client_name") or "").strip()
    duration = int(request.form.get("duration") or 10)
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    start_time = (request.form.get("start_time") or "").strip()
    end_time = (request.form.get("end_time") or "").strip()
    target_screen = request.form.get("target_screen") or ""

    uploaded_ids = []
    with db() as c:
        for idx, f in enumerate(files):
            if not f or not f.filename:
                continue
            ext = os.path.splitext(f.filename)[1].lower()
            kind = "video" if ext in VIDEO else "image" if ext in IMAGE else None
            if not kind:
                msg = f"Formato '{ext}' não suportado. Use MP4, WEBM, MOV, JPG, PNG, GIF ou WEBP."
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"error": msg}), 400
                return msg, 400

            fname = secrets.token_hex(8) + ext
            fpath = os.path.join(UP, fname)
            f.save(fpath)
            fsize = os.path.getsize(fpath) if os.path.exists(fpath) else 0

            if custom_name:
                item_name = custom_name if len(files) == 1 else f"{custom_name} ({idx + 1})"
            else:
                item_name = os.path.splitext(f.filename)[0]

            cur = c.execute("""
                INSERT INTO media(name, kind, file, duration, client_name, active, start_date, end_date, start_time, end_time, file_size, created_at)
                VALUES(?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """, (item_name, kind, fname, duration, client_name, start_date, end_date, start_time, end_time, fsize, time.time()))
            mid = cur.lastrowid
            uploaded_ids.append(mid)

            # Automatically add to screen(s) if requested
            if target_screen == "all":
                for s in c.execute("SELECT id FROM screens").fetchall():
                    p = c.execute("SELECT COALESCE(MAX(pos),0)+1 FROM items WHERE screen_id=?", (s["id"],)).fetchone()[0]
                    c.execute("INSERT INTO items(screen_id, media_id, pos, active) VALUES(?, ?, ?, 1)", (s["id"], mid, p))
            elif target_screen.isdigit():
                sid = int(target_screen)
                p = c.execute("SELECT COALESCE(MAX(pos),0)+1 FROM items WHERE screen_id=?", (sid,)).fetchone()[0]
                c.execute("INSERT INTO items(screen_id, media_id, pos, active) VALUES(?, ?, ?, 1)", (sid, mid, p))

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "uploaded": len(uploaded_ids)})
    return redirect("/")


@app.post("/media/<int:i>/edit")
@auth
def edit_media(i):
    name = (request.form.get("name") or "").strip()
    client_name = (request.form.get("client_name") or "").strip()
    duration = int(request.form.get("duration") or 10)
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    start_time = (request.form.get("start_time") or "").strip()
    end_time = (request.form.get("end_time") or "").strip()

    with db() as c:
        c.execute("""
            UPDATE media
            SET name=?, client_name=?, duration=?, start_date=?, end_date=?, start_time=?, end_time=?
            WHERE id=?
        """, (name or "Mídia", client_name, duration, start_date, end_date, start_time, end_time, i))
    return redirect("/")


@app.post("/media/<int:i>/toggle")
@auth
def toggle_media(i):
    with db() as c:
        r = c.execute("SELECT active FROM media WHERE id=?", (i,)).fetchone()
        if r:
            new_val = 0 if r["active"] else 1
            c.execute("UPDATE media SET active=? WHERE id=?", (new_val, i))
    return redirect("/")


@app.post("/media/<int:i>/delete")
@auth
def del_media(i):
    with db() as c:
        r = c.execute("SELECT file FROM media WHERE id=?", (i,)).fetchone()
        if r:
            try:
                os.remove(os.path.join(UP, r["file"]))
            except OSError:
                pass
        c.execute("DELETE FROM items WHERE media_id=?", (i,))
        c.execute("DELETE FROM media WHERE id=?", (i,))
    return redirect("/")


@app.post("/screens")
@auth
def new_screen():
    name = (request.form.get("name") or "Painel LED").strip()
    fit_mode = request.form.get("fit_mode") or "cover"
    rotation = int(request.form.get("rotation") or 0)
    muted = 0 if request.form.get("sound") == "1" else 1
    transition = request.form.get("transition") or "fade"
    resolution = (request.form.get("resolution") or "1920x1080").strip()

    with db() as c:
        c.execute(
            "INSERT INTO screens(name, slug, fit_mode, rotation, muted, transition, resolution) VALUES(?,?,?,?,?,?,?)",
            (name, secrets.token_hex(3), fit_mode, rotation, muted, transition, resolution)
        )
    return redirect("/")


@app.post("/screens/<int:i>/settings")
@auth
def edit_screen(i):
    name = (request.form.get("name") or "Painel LED").strip()
    fit_mode = request.form.get("fit_mode") or "cover"
    rotation = int(request.form.get("rotation") or 0)
    muted = 0 if request.form.get("sound") == "1" else 1
    transition = request.form.get("transition") or "fade"
    resolution = (request.form.get("resolution") or "1920x1080").strip()

    with db() as c:
        c.execute("""
            UPDATE screens
            SET name=?, fit_mode=?, rotation=?, muted=?, transition=?, resolution=?
            WHERE id=?
        """, (name, fit_mode, rotation, muted, transition, resolution, i))
    return redirect("/")


@app.post("/screens/<int:i>/delete")
@auth
def del_screen(i):
    with db() as c:
        c.execute("DELETE FROM items WHERE screen_id=?", (i,))
        c.execute("DELETE FROM screens WHERE id=?", (i,))
    return redirect("/")


@app.post("/screens/<int:i>/add")
@auth
def add_item(i):
    mid = request.form.get("media_id")
    if mid:
        with db() as c:
            if mid == "all":
                for m in c.execute("SELECT id FROM media WHERE active=1 ORDER BY id DESC").fetchall():
                    p = c.execute("SELECT COALESCE(MAX(pos),0)+1 FROM items WHERE screen_id=?", (i,)).fetchone()[0]
                    c.execute("INSERT INTO items(screen_id, media_id, pos, active) VALUES(?,?,?,1)", (i, m["id"], p))
            else:
                p = c.execute("SELECT COALESCE(MAX(pos),0)+1 FROM items WHERE screen_id=?", (i,)).fetchone()[0]
                c.execute("INSERT INTO items(screen_id, media_id, pos, active) VALUES(?,?,?,1)", (i, mid, p))
    return redirect("/")


@app.post("/screens/<int:i>/clear")
@auth
def clear_screen_playlist(i):
    with db() as c:
        c.execute("DELETE FROM items WHERE screen_id=?", (i,))
    return redirect("/")


@app.post("/items/<int:i>/<act>")
@auth
def item_act(i, act):
    with db() as c:
        it = c.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone()
        if not it:
            return redirect("/")
        if act == "delete":
            c.execute("DELETE FROM items WHERE id=?", (i,))
        elif act == "toggle":
            new_val = 0 if it["active"] else 1
            c.execute("UPDATE items SET active=? WHERE id=?", (new_val, i))
        elif act in ("up", "down"):
            ids = [r["id"] for r in c.execute("SELECT id FROM items WHERE screen_id=? ORDER BY pos, id", (it["screen_id"],))]
            if i in ids:
                k = ids.index(i)
                j = k - 1 if act == "up" else k + 1
                if 0 <= j < len(ids):
                    ids[k], ids[j] = ids[j], ids[k]
                    for n, rid in enumerate(ids):
                        c.execute("UPDATE items SET pos=? WHERE id=?", (n, rid))
    return redirect("/")


@app.post("/settings")
@auth
def update_settings():
    brand_name = (request.form.get("brand_name") or "").strip()
    if brand_name:
        set_setting("brand_name", brand_name)

    new_pass = request.form.get("new_password") or ""
    if new_pass.strip():
        set_setting("admin_password_hash", generate_password_hash(new_pass.strip()))

    return redirect("/")


@app.route("/player/<slug>")
def player(slug):
    with db() as c:
        s = c.execute("SELECT * FROM screens WHERE slug=?", (slug,)).fetchone()
        if not s:
            abort(404)
    brand_name = get_setting("brand_name", "Shop Cor Tintas")
    return render_template("player.html", slug=slug, screen=dict(s), brand_name=brand_name)


@app.route("/manifest/<slug>.json")
def player_manifest(slug):
    with db() as c:
        s = c.execute("SELECT * FROM screens WHERE slug=?", (slug,)).fetchone()
    name = s["name"] if s else "Painel LED"
    return jsonify({
        "name": f"Player LED - {name}",
        "short_name": name,
        "start_url": f"/player/{slug}",
        "display": "fullscreen",
        "orientation": "any",
        "background_color": "#000000",
        "theme_color": "#000000"
    })


@app.route("/api/playlist/<slug>")
def playlist(slug):
    now_playing = request.args.get("playing", "")
    with db() as c:
        s = c.execute("SELECT * FROM screens WHERE slug=?", (slug,)).fetchone()
        if not s:
            abort(404)
        if now_playing:
            c.execute("UPDATE screens SET seen=?, current_media=? WHERE id=?", (time.time(), now_playing, s["id"]))
        else:
            c.execute("UPDATE screens SET seen=? WHERE id=?", (time.time(), s["id"]))

        rows = c.execute("""
            SELECT i.id as item_id, i.active as item_active,
                   m.id as media_id, m.name, m.kind, m.file, m.duration,
                   m.active, m.start_date, m.end_date, m.start_time, m.end_time
            FROM items i
            JOIN media m ON m.id = i.media_id
            WHERE i.screen_id = ?
            ORDER BY i.pos, i.id
        """, (s["id"],)).fetchall()

    items_out = []
    for r in rows:
        rd = dict(r)
        if not rd.get("item_active", 1):
            continue
        st_code, _ = get_media_schedule_status(rd)
        if st_code != "active":
            continue
        items_out.append({
            "id": rd["item_id"],
            "media_id": rd["media_id"],
            "name": rd["name"],
            "kind": rd["kind"],
            "url": "/m/" + rd["file"],
            "duration": int(rd["duration"] or 10)
        })

    return jsonify({
        "screen": {
            "name": s["name"],
            "slug": s["slug"],
            "fit_mode": s["fit_mode"] or "cover",
            "rotation": int(s["rotation"] or 0),
            "muted": bool(s["muted"]) if s["muted"] is not None else True,
            "transition": s["transition"] or "fade",
            "resolution": s["resolution"] or "1920x1080",
        },
        "items": items_out,
        "server_time": time.time()
    })


@app.route("/api/status")
@auth
def api_status():
    with db() as c:
        screens = []
        for s in c.execute("SELECT id, name, slug, seen, current_media FROM screens ORDER BY id").fetchall():
            is_online = (time.time() - (s["seen"] or 0)) < 90
            screens.append({
                "id": s["id"],
                "online": is_online,
                "current_media": s["current_media"] or ""
            })
    return jsonify({"screens": screens})


@app.route("/m/<path:f>")
def media_file(f):
    response = send_from_directory(UP, f, conditional=True)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.route("/tvbox")
def tvbox_downloads():
    apk_dir = os.path.join(BASE, "sistema-tvbox-mxq4k", "instalar-no-pendrive")
    files = [f for f in os.listdir(apk_dir) if f.endswith(".apk") or f.endswith(".txt")]
    links_html = "".join([f"<li style='margin: 15px 0;'><a style='font-size: 22px; color: #0288d1; text-decoration: none; font-weight: bold;' href='/tvbox/download/{f}'>📥 Baixar {f}</a></li>" for f in files])
    return f"""
    <!doctype html>
    <html lang="pt-BR">
    <head><meta charset="utf-8"><title>Aplicativos TV Box</title></head>
    <body style="font-family: sans-serif; background: #0f131c; color: #fff; padding: 30px;">
        <h1 style="color: #fb8c00;">Aplicativos para TV Box MXQ 4K</h1>
        <p style="font-size: 18px; color: #aaa;">Clique abaixo para baixar e instalar direto na sua TV Box:</p>
        <ul style="list-style: none; padding: 0;">{links_html}</ul>
        <hr style="border-color: #333; margin-top: 30px;">
        <p style="color: #888;">Shop Cor Tintas - Painel LED</p>
    </body>
    </html>
    """


@app.route("/tvbox/download/<path:f>")
def tvbox_file(f):
    apk_dir = os.path.join(BASE, "sistema-tvbox-mxq4k", "instalar-no-pendrive")
    return send_from_directory(apk_dir, f, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    local_ip = get_local_ip()
    try:
        print("=" * 60)
        print("  PAINEL DE MIDIA LED - SERVIDOR ATIVO")
        print(f"  No computador: http://localhost:{port}")
        print(f"  Na rede/Wi-Fi: http://{local_ip}:{port}")
        print("=" * 60)
    except Exception:
        pass
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
