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

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

VIDEO = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}
IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
HTML = {".html", ".htm"}


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
        
        CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            email TEXT DEFAULT '',
            source TEXT DEFAULT 'whatsapp',
            status TEXT DEFAULT 'novo',
            value REAL DEFAULT 0,
            items_text TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY,
            order_code TEXT UNIQUE,
            customer_name TEXT,
            customer_phone TEXT,
            customer_address TEXT DEFAULT '',
            payment_method TEXT DEFAULT 'pix',
            shipping_method TEXT DEFAULT 'Entrega',
            shipping_cost REAL DEFAULT 0,
            subtotal REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'pendente',
            items_json TEXT DEFAULT '[]',
            created_at REAL DEFAULT 0
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
        
        # Seed realistic CRM leads if empty
        if c.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0:
            now = time.time()
            sample_leads = [
                ("Clodoaldo Pintor", "(19) 99841-2233", "whatsapp", "novo", 180.0, "1x Massa Corrida Lukscolor 18L + 2x Rolo Lã", "Pediu preço pelo WhatsApp às 14:20", now - 3600),
                ("Juliana M. Fachada", "(19) 98765-4321", "instagram", "novo", 650.0, "Tinta Emborrachada Fachada 18L", "Veio de anúncio Instagram Limeira", now - 7200),
                ("Funilaria Alemão", "(19) 99234-5678", "whatsapp", "qualificado", 510.0, "3x Autoluks PU Preto Cadillac + Primer Rápido", "Mandou áudio de 28s transcrito pelo Whisper", now - 1800),
                ("Carlos Eduardo Eng.", "(19) 98112-9988", "site", "qualificado", 1140.0, "Kit Pintura Interna: 2x 18L Tradição + Selador", "Montou kit no site para obra em Cordeirópolis", now - 5400),
                ("Marcelo Acabamentos", "(19) 99345-6789", "whatsapp", "orcamento", 890.0, "Orçamento completo faturado para 15 dias", "Aguardando aprovação do cliente dele", now - 14400),
                ("Lucas Ferreira", "(19) 98822-1144", "site", "aguardando", 554.31, "Pedido #SC-4821: 1x Tradição 18L Semibrilho + 2x Rolo", "Chave Pix gerada no checkout do site", now - 900),
                ("Pinturas Silva & Filhos", "(19) 99765-1122", "whatsapp", "fechado", 1480.0, "4x 18L Tradição Branco Neve + Fitas", "Venda fechada, motorista saiu para entrega", now - 28800)
            ]
            c.executemany("INSERT INTO leads(name, phone, source, status, value, items_text, notes, created_at) VALUES(?,?,?,?,?,?,?,?)", sample_leads)

        # Seed realistic orders if empty
        if c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            now = time.time()
            sample_orders = [
                ("SC-4821", "Lucas Ferreira", "(19) 98822-1144", "Rua Santa Cruz, 450 - Centro, Limeira/SP", "pix", "Entrega Expressa Shop Cor (Limeira)", 0.0, 554.31, 0.0, 554.31, "pago", now - 900),
                ("SC-4820", "Oficina Auto Rápido", "(19) 99112-3344", "Retirada no Balcão da Loja Física", "entrega", "Retirada na Loja Física (Limeira)", 0.0, 280.0, 0.0, 280.0, "separacao", now - 7200),
                ("SC-4819", "Condomínio Campinas", "(19) 97123-5566", "Av. Brasil, 1200 - Campinas/SP", "cartao", "Transportadora Rodoviária Jadlog", 38.0, 654.0, 0.0, 692.0, "em_rota", now - 21600)
            ]
            c.executemany("INSERT INTO orders(order_code, customer_name, customer_phone, customer_address, payment_method, shipping_method, shipping_cost, subtotal, discount, total, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", sample_orders)

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

    with db() as c:
        crm_leads = [dict(r) for r in c.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()]
        recent_orders = [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()]
    crm_stats = {
        "total_leads": len(crm_leads),
        "pipeline_value": sum(float(l.get("value") or 0) for l in crm_leads),
        "total_orders": len(recent_orders),
        "orders_revenue": sum(float(o.get("total") or 0) for o in recent_orders if o.get("status") in ["pago", "separacao", "em_rota", "entregue"])
    }
    return render_template(
        "admin.html",
        crm_leads=crm_leads,
        recent_orders=recent_orders,
        crm_stats=crm_stats,
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
            kind = "video" if ext in VIDEO else "image" if ext in IMAGE else "html" if ext in HTML else None
            if not kind:
                msg = f"Formato '{ext}' não suportado. Use MP4, WEBM, MOV, JPG, PNG, GIF, WEBP ou HTML."
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



# ==========================================
# ROTAS DO E-COMMERCE & LOJA VIRTUAL
# ==========================================
@app.route("/loja")
@app.route("/loja/")
def loja_home():
    loja_dir = os.path.join(BASE, "loja_static")
    if os.path.exists(os.path.join(loja_dir, "index.html")):
        return send_from_directory(loja_dir, "index.html")
    return "Loja em manutenção", 404

@app.route("/loja/<path:filename>")
def loja_static_files(filename):
    loja_dir = os.path.join(BASE, "loja_static")
    return send_from_directory(loja_dir, filename)

@app.route("/api/catalog")
@app.route("/api/catalog.json")
@app.route("/loja/api/catalog")
@app.route("/loja/api/catalog.json")
def serve_catalog():
    loja_dir = os.path.join(BASE, "loja_static")
    for f in ["catalog.json", "catalog"]:
        p = os.path.join(loja_dir, "api", f)
        if os.path.exists(p):
            return send_from_directory(os.path.join(loja_dir, "api"), f, mimetype="application/json")
    return jsonify({"items": [], "version": "1.0"})

# ==========================================
# ROTAS DE PEDIDOS (E-COMMERCE CHECKOUT)
# ==========================================
@app.route("/api/orders", methods=["GET", "POST"])
def handle_orders():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        code = data.get("order_code") or f"SC-{secrets.randbelow(9000)+1000}"
        total = float(data.get("total", 0))
        cust_name = data.get("customer_name") or data.get("name") or "Cliente Site"
        cust_phone = data.get("customer_phone") or data.get("phone") or ""
        cust_addr = data.get("customer_address") or data.get("address") or ""
        pay_method = data.get("payment_method") or "pix"
        ship_method = data.get("shipping_method") or "Entrega"
        ship_cost = float(data.get("shipping_cost", 0))
        subtotal = float(data.get("subtotal", total))
        discount = float(data.get("discount", 0))

        with db() as c:
            c.execute("""
                INSERT INTO orders(order_code, customer_name, customer_phone, customer_address, payment_method, shipping_method, shipping_cost, subtotal, discount, total, status, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (code, cust_name, cust_phone, cust_addr, pay_method, ship_method, ship_cost, subtotal, discount, total, "pendente", time.time()))
            
            # Auto-insert into CRM Leads
            c.execute("""
                INSERT INTO leads(name, phone, source, status, value, items_text, notes, created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (cust_name, cust_phone, "site", "aguardando", total, f"Pedido #{code}", f"Endereço: {cust_addr}", time.time()))

        return jsonify({"status": "ok", "order_code": code})

    with db() as c:
        orders = [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()]
    return jsonify({"orders": orders})

@app.route("/api/orders/<int:order_id>/status", methods=["POST"])
@auth
def update_order_status(order_id):
    data = request.get_json(silent=True) or request.form.to_dict()
    st = data.get("status", "pendente")
    with db() as c:
        c.execute("UPDATE orders SET status=? WHERE id=?", (st, order_id))
    return jsonify({"status": "ok"})

# ==========================================
# ROTAS DO CRM KANBAN
# ==========================================
@app.route("/api/crm/leads", methods=["GET", "POST"])
@auth
def handle_crm_leads():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        with db() as c:
            c.execute("""
                INSERT INTO leads(name, phone, email, source, status, value, items_text, notes, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                data.get("name", "Novo Lead"),
                data.get("phone", ""),
                data.get("email", ""),
                data.get("source", "whatsapp"),
                data.get("status", "novo"),
                float(data.get("value", 0)),
                data.get("items_text", ""),
                data.get("notes", ""),
                time.time()
            ))
        return jsonify({"status": "ok"})

    with db() as c:
        leads = [dict(r) for r in c.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()]
    return jsonify({"leads": leads})

@app.route("/api/crm/leads/<int:lead_id>/status", methods=["POST"])
@auth
def move_crm_lead(lead_id):
    data = request.get_json(silent=True) or request.form.to_dict()
    new_status = data.get("status", "novo")
    with db() as c:
        c.execute("UPDATE leads SET status=? WHERE id=?", (new_status, lead_id))
    return jsonify({"status": "ok"})

@app.route("/api/crm/leads/<int:lead_id>/delete", methods=["POST"])
@auth
def delete_crm_lead(lead_id):
    with db() as c:
        c.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    return jsonify({"status": "ok"})

# Webhook para n8n integration
@app.route("/api/n8n/webhook", methods=["POST"])
def n8n_webhook():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "lead_create")
    with db() as c:
        if action == "lead_create":
            c.execute("""
                INSERT INTO leads(name, phone, source, status, value, items_text, notes, created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (
                data.get("name", "Lead WhatsApp"),
                data.get("phone", ""),
                data.get("source", "whatsapp"),
                data.get("status", "qualificado"),
                float(data.get("value", 0)),
                data.get("items_text", ""),
                data.get("notes", "Recebido via n8n SDR"),
                time.time()
            ))
        elif action == "lead_status" and "lead_id" in data:
            c.execute("UPDATE leads SET status=? WHERE id=?", (data.get("status", "qualificado"), data["lead_id"]))
    return jsonify({"status": "ok", "received": True})


# ==========================================
# ROTAS DO APLICATIVO DE CONTROLE DE ENTREGAS & ROTAS (GPS / MOTORISTAS)
# ==========================================
@app.route("/rotas")
@app.route("/entregas")
def controle_rotas():
    return render_template("controle_rotas.html")


# ==========================================
# SIMULADOR PÚBLICO DO SDR WHATSAPP (SEM LOGIN - PARA TESTES EXTERNOS)
# ==========================================
@app.route("/simulador")
@app.route("/teste-sdr")
def simulador_publico():
    return render_template("simulador_sdr.html")


# ==========================================
# MOTOR DE VOZ IA (VOZ NEURAL BRASILEIRA NATURAL + ELEVENLABS CLONE)
# ==========================================
TTS_CACHE_DIR = os.path.join(BASE, "static", "tts_cache")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "sk_6519acd093df59dc63582e6fcc018fde221734ccd9df6920")
CLONED_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")

VOICE_CONFIGS = {
    "francisca": ("pt-BR-FranciscaNeural", "+6%", "+0Hz"),
    "thalita": ("pt-BR-ThalitaMultilingualNeural", "+6%", "+0Hz"),
    "antonio": ("pt-BR-AntonioNeural", "+6%", "+0Hz")
}

@app.route("/api/tts", methods=["GET", "POST"])
def get_tts_audio():
    import hashlib, re
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        vchoice = data.get("voice", "francisca").lower()
    else:
        text = request.args.get("text", "")
        vchoice = request.args.get("voice", "francisca").lower()
    
    text = text.strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
        
    clean_text = re.sub(r'<[^>]+>', ' ', text).strip()
    voice_key = vchoice if vchoice in VOICE_CONFIGS else "francisca"
    voice_name, voice_rate, voice_pitch = VOICE_CONFIGS[voice_key]
    
    voice_tag = CLONED_VOICE_ID if (CLONED_VOICE_ID and voice_key == "clone") else voice_name
    h = hashlib.md5((clean_text + voice_tag + voice_rate).encode('utf-8')).hexdigest()
    filename = f"{h}.mp3"
    filepath = os.path.join(TTS_CACHE_DIR, filename)
    
    if not os.path.exists(filepath):
        success = False
        # 1. Se o usuario solicitar clone e houver voz ativa no ElevenLabs
        if voice_key == "clone" and CLONED_VOICE_ID and ELEVENLABS_API_KEY:
            try:
                import requests
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{CLONED_VOICE_ID}"
                headers = {
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json"
                }
                payload = {
                    "text": clean_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.55,
                        "similarity_boost": 0.85
                    }
                }
                r = requests.post(url, headers=headers, json=payload, timeout=12)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    success = True
            except Exception as e:
                print(f"ElevenLabs TTS erro: {e}")

        # 2. Vozes Neurais Brasileiras de Alta Fidelidade (Microsoft Neural pt-BR)
        if not success:
            try:
                import asyncio, edge_tts
                async def run_tts():
                    comm = edge_tts.Communicate(clean_text, voice_name, rate=voice_rate, pitch=voice_pitch)
                    await comm.save(filepath)
                asyncio.run(run_tts())
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            
    return send_from_directory(TTS_CACHE_DIR, filename, mimetype="audio/mpeg")


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
