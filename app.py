from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import os, uuid

from PIL import Image

def compress_image_inplace(abs_path:str, max_long:int, jpg_quality:int):
    """
    Open image at abs_path, resize to keep long edge <= max_long, and re-save:
      - If original has alpha channel, keep PNG (optimize).
      - Otherwise, save as JPEG with given quality (optimize, progressive).
    The function overwrites the file and may change extension to .jpg if converted.
    Returns possibly updated absolute path and relative filename.
    """
    try:
        img = Image.open(abs_path)
    except Exception:
        return abs_path  # skip if cannot open

    # Compute new size if needed
    w, h = img.size
    scale = 1.0
    if max(w, h) > max_long:
        scale = max_long / float(max(w, h))
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Determine if alpha exists
    has_alpha = (img.mode in ("RGBA", "LA")) or ("transparency" in img.info)
    folder = os.path.dirname(abs_path)
    name_no_ext, ext = os.path.splitext(os.path.basename(abs_path))

    if has_alpha:
        # Keep PNG
        target_path = os.path.join(folder, f"{name_no_ext}.png")
        # Convert to RGBA to be safe
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.save(target_path, format="PNG", optimize=True, compress_level=9)
    else:
        # Convert to RGB for JPEG
        if img.mode != "RGB":
            img = img.convert("RGB")
        target_path = os.path.join(folder, f"{name_no_ext}.jpg")
        img.save(target_path, format="JPEG", quality=jpg_quality, optimize=True, progressive=True)

    # If we changed extension, remove old file
    if os.path.normpath(target_path) != os.path.normpath(abs_path):
        try:
            os.remove(abs_path)
        except Exception:
            pass
    return target_path


load_dotenv()

# --- Basic Config ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")
db_url = os.getenv("DATABASE_URL", "sqlite:///data.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")

# Max upload size
max_mb = float(os.getenv("MAX_CONTENT_MB", "30"))
app.config["MAX_CONTENT_LENGTH"] = int(max_mb * 1024 * 1024)  # bytes
# Image compression configs
max_img_long = int(os.getenv("MAX_IMG_LONG", "1920"))
jpg_quality = int(os.getenv("JPEG_QUALITY", "85"))


ALLOWED_EXTENSIONS = {"png","jpg","jpeg","gif","webp"}

# GM Accounts (very simple auth for demo)
GM_ACCOUNTS = {
    os.getenv("ADMIN1_USERNAME", "gm1"): os.getenv("ADMIN1_PASSWORD", "gm1password"),
    os.getenv("ADMIN2_USERNAME", "gm2"): os.getenv("ADMIN2_PASSWORD", "gm2password")
}

db = SQLAlchemy(app)

# --- Models ---
class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.String(64), nullable=False, index=True)
    prereg_1 = db.Column(db.String(255), nullable=False)
    prereg_2 = db.Column(db.String(255), nullable=False)
    discord_1 = db.Column(db.String(255), nullable=False)
    discord_2 = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # reward status
    is_granted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    granted_by = db.Column(db.String(64), nullable=True)
    granted_at = db.Column(db.DateTime, nullable=True)

class DailyTweet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.String(64), nullable=False, index=True)
    image_path = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # reward status
    is_granted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    granted_by = db.Column(db.String(64), nullable=True)
    granted_at = db.Column(db.DateTime, nullable=True)

# --- Helpers ---
def allowed_file(filename: str, mimetype: str = "") -> bool:
    ext_ok = ("." in (filename or "")) and (filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS)
    type_ok = mimetype.startswith("image/") if mimetype else False
    return ext_ok or type_ok

def save_image(file_storage, subdir):
    """Save under uploads/subdir, then auto-compress. Handles files with/without extension."""
    if not (file_storage and (file_storage.filename or "").strip()):
        return None

    # Create folder
    uploads_root = app.config["UPLOAD_FOLDER"]
    folder = os.path.join(uploads_root, subdir)
    os.makedirs(folder, exist_ok=True)

    # Build a safe base name (no extension needed yet)
    orig = secure_filename(file_storage.filename or "image")
    base = os.path.splitext(orig)[0] or "image"
    unique = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    temp_path = os.path.join(folder, f"{base}-{unique}.tmp")

    # Save raw upload to tmp first
    file_storage.save(temp_path)

    # Compress -> returns final absolute path with proper extension (jpg/png)
    final_abs = compress_image_inplace(temp_path, max_img_long, jpg_quality)

    # Normalize & compute relative path (make uploads_root absolute to avoid Windows issues)
    uploads_root_abs = os.path.abspath(uploads_root)
    final_abs_norm = os.path.abspath(final_abs)
    rel = os.path.relpath(final_abs_norm, uploads_root_abs)
    return rel.replace("\\", "/")


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(e):
    flash(f"檔案總大小超過限制：{max_mb} MB。請減少檔案大小或數量。", "error")
    return redirect(request.referrer or url_for("index"))

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    game_id = request.form.get("game_id", "").strip()
    notes = request.form.get("notes", "").strip()

    # Required fields
    prereg_1 = request.files.get("prereg_1")
    prereg_2 = request.files.get("prereg_2")
    discord_1 = request.files.get("discord_1")
    discord_2 = request.files.get("discord_2")

    if not game_id:
        flash("請輸入『遊戲 ID』（必填）。", "error")
        return redirect(url_for("index"))

    # Validate required images
    required = [("事前預約(1)", prereg_1), ("事前預約(2)", prereg_2),
                ("Discord 推廣(1)", discord_1), ("Discord 推廣(2)", discord_2)]
    for label, f in required:
        if f is None or f.filename == "":
            flash(f"請上傳『{label}』圖片。", "error")
            return redirect(url_for("index"))
        if not allowed_file(f.filename, getattr(f, 'mimetype', '')):
            flash(f"『{label}』檔案格式不支援。允許：{', '.join(sorted(ALLOWED_EXTENSIONS))}", "error")
            return redirect(url_for("index"))

    # Save files
    p1 = save_image(prereg_1, "prereg")
    p2 = save_image(prereg_2, "prereg")
    d1 = save_image(discord_1, "discord")
    d2 = save_image(discord_2, "discord")

    # Write DB
    sub = Submission(game_id=game_id, prereg_1=p1, prereg_2=p2, discord_1=d1, discord_2=d2, notes=notes)
    db.session.add(sub)
    db.session.commit()

    return render_template("success.html", mode="init", game_id=game_id)

@app.route("/daily")
def daily():
    return render_template("daily.html")

@app.route("/daily_upload", methods=["POST"])
def daily_upload():
    game_id = request.form.get("game_id", "").strip()
    notes = request.form.get("notes", "").strip()
    files = request.files.getlist("tweet_images")

    if not game_id:
        flash("請輸入『遊戲 ID』（必填）。", "error")
        return redirect(url_for("daily"))

    if not files or all(f.filename == "" for f in files):
        flash("請至少上傳 1 張『每日推文』截圖。", "error")
        return redirect(url_for("daily"))

    # Save each image
    saved_any = False
    for f in files:
        if f and f.filename != "":
            if not allowed_file(f.filename, getattr(f, 'mimetype', '')):
                flash("部分檔案格式不支援，請僅上傳圖片檔（png/jpg/jpeg/gif/webp）。", "error")
                return redirect(url_for("daily"))
            rel = save_image(f, "tweets")
            tweet = DailyTweet(game_id=game_id, image_path=rel, notes=notes)
            db.session.add(tweet)
            saved_any = True

    if saved_any:
        db.session.commit()
        return render_template("success.html", mode="daily", game_id=game_id)
    else:
        flash("沒有成功儲存任何圖片。", "error")
        return redirect(url_for("daily"))

# --- Public serving for uploaded files (optional; for quick demo) ---
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # NOTE: In production, serve static files via Nginx or a CDN instead.
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

# --- GM (Admin) ---
@app.route("/gm/login", methods=["GET", "POST"])
def gm_login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        if u in GM_ACCOUNTS and GM_ACCOUNTS[u] == p:
            session["gm_user"] = u
            return redirect(url_for("gm_dashboard"))
        else:
            flash("帳號或密碼錯誤。", "error")
    return render_template("admin_login.html")

@app.route("/gm/logout")
def gm_logout():
    session.pop("gm_user", None)
    flash("已登出。", "info")
    return redirect(url_for("gm_login"))

def require_gm():
    if "gm_user" not in session:
        return False
    return True


@app.route("/gm/mark/submission/<int:sid>")
def gm_mark_submission(sid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    sub = Submission.query.get_or_404(sid)
    sub.is_granted = not sub.is_granted
    sub.granted_by = session.get("gm_user")
    sub.granted_at = datetime.utcnow()
    db.session.commit()
    flash(f"已切換首次資料 #{sid} 的發放狀態為：{'已發放' if sub.is_granted else '未發放'}", "info")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end","")))

@app.route("/gm/mark/tweet/<int:tid>")
def gm_mark_tweet(tid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    t = DailyTweet.query.get_or_404(tid)
    t.is_granted = not t.is_granted
    t.granted_by = session.get("gm_user")
    t.granted_at = datetime.utcnow()
    db.session.commit()
    flash(f"已切換每日推文 #{tid} 的發放狀態為：{'已發放' if t.is_granted else '未發放'}", "info")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end","")))


@app.route("/gm/batch_mark", methods=["POST"])
def gm_batch_mark():
    if not require_gm():
        return redirect(url_for("gm_login"))
    ids = request.form.getlist("ids")
    table = request.form.get("table")
    if ids:
        if table == "submission":
            for sid in ids:
                s = Submission.query.get(int(sid))
                if s and not s.is_granted:
                    s.is_granted = True
                    s.granted_by = session.get("gm_user")
                    s.granted_at = datetime.utcnow()
        elif table == "tweet":
            for tid in ids:
                t = DailyTweet.query.get(int(tid))
                if t and not t.is_granted:
                    t.is_granted = True
                    t.granted_by = session.get("gm_user")
                    t.granted_at = datetime.utcnow()
        db.session.commit()
        flash(f"已批次標註 {len(ids)} 筆為已發放", "info")
    return redirect(url_for("gm_dashboard",
                            q=request.args.get("q",""),
                            start=request.args.get("start",""),
                            end=request.args.get("end",""),
                            status=request.args.get("status","")))

@app.route("/gm")
def gm_dashboard():
    if not require_gm():
        return redirect(url_for("gm_login"))
    # Filters
    q = request.args.get("q","").strip()
    # Date filters (YYYY-MM-DD)
    start = request.args.get("start","").strip()
    end = request.args.get("end","").strip()
    status_filter = request.args.get("status","").strip()

    subs = Submission.query
    tweets = DailyTweet.query

    if q:
        subs = subs.filter(Submission.game_id.like(f"%{q}%"))
        tweets = tweets.filter(DailyTweet.game_id.like(f"%{q}%"))

    # Apply date filter if provided
    def parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None

    start_dt = parse_date(start)
    end_dt = parse_date(end)
    if start_dt:
        subs = subs.filter(Submission.created_at >= start_dt)
        tweets = tweets.filter(DailyTweet.created_at >= start_dt)
    if end_dt:
        # include entire end day
        end_of_day = end_dt.replace(hour=23, minute=59, second=59)
        subs = subs.filter(Submission.created_at <= end_of_day)
        tweets = tweets.filter(DailyTweet.created_at <= end_of_day)

    # Status filter: "granted" or "pending"
    if status_filter == "granted":
        subs = subs.filter(Submission.is_granted == True)
        tweets = tweets.filter(DailyTweet.is_granted == True)
    elif status_filter == "pending":
        subs = subs.filter(Submission.is_granted == False)
        tweets = tweets.filter(DailyTweet.is_granted == False)

    subs = subs.order_by(Submission.created_at.desc()).all()
    tweets = tweets.order_by(DailyTweet.created_at.desc()).all()

    return render_template("admin_dashboard.html", subs=subs, tweets=tweets, q=q, start=start, end=end, status=status_filter)

@app.route("/gm/submission/<int:sid>")
def gm_view_submission(sid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    sub = Submission.query.get_or_404(sid)
    return render_template("view_submission.html", sub=sub)

# --- Init DB ---
with app.app_context():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()

# --- Simple auto-migration for new columns (SQLite) ---
with app.app_context():
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    # (table, column, ddl)
    alters = [
        ("submission", "is_granted", "ALTER TABLE submission ADD COLUMN is_granted BOOLEAN NOT NULL DEFAULT 0"),
        ("submission", "granted_by", "ALTER TABLE submission ADD COLUMN granted_by VARCHAR(64)"),
        ("submission", "granted_at", "ALTER TABLE submission ADD COLUMN granted_at DATETIME"),
        ("daily_tweet", "is_granted", "ALTER TABLE daily_tweet ADD COLUMN is_granted BOOLEAN NOT NULL DEFAULT 0"),
        ("daily_tweet", "granted_by", "ALTER TABLE daily_tweet ADD COLUMN granted_by VARCHAR(64)"),
        ("daily_tweet", "granted_at", "ALTER TABLE daily_tweet ADD COLUMN granted_at DATETIME"),
    ]
    for table, col, ddl in alters:
        cols = [c['name'] for c in insp.get_columns(table)] if insp.has_table(table) else []
        if col not in cols:
            try:
                db.session.execute(text(ddl))
                db.session.commit()
            except Exception:
                db.session.rollback()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
