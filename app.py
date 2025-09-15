from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import os, uuid

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")
db_url = os.getenv("DATABASE_URL", "sqlite:///data.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

max_mb = float(os.getenv("MAX_CONTENT_MB", "100"))
app.config["MAX_CONTENT_LENGTH"] = int(max_mb * 1024 * 1024)

# Compression configs
max_img_long = int(os.getenv("MAX_IMG_LONG", "1600"))
jpg_quality = int(os.getenv("JPEG_QUALITY", "80"))

ALLOWED_EXTENSIONS = {"png","jpg","jpeg","gif","webp"}

from PIL import Image

def allowed_file(filename: str, mimetype: str = "") -> bool:
    ext_ok = ("." in (filename or "")) and (filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS)
    type_ok = mimetype.startswith("image/") if mimetype else False
    return ext_ok or type_ok

def compress_image_inplace(abs_path:str, max_long:int, jpg_quality:int):
    """Open image at abs_path, resize to keep long edge <= max_long, and re-save as JPEG (no alpha) or PNG (alpha)."""
    try:
        img = Image.open(abs_path)
    except Exception:
        return abs_path
    w, h = img.size
    if max(w, h) > max_long:
        scale = max_long / float(max(w, h))
        img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    has_alpha = (img.mode in ("RGBA","LA")) or ("transparency" in img.info)
    folder = os.path.dirname(abs_path)
    name_no_ext = os.path.splitext(os.path.basename(abs_path))[0]
    if has_alpha:
        if img.mode not in ("RGB","RGBA"):
            img = img.convert("RGBA")
        target_path = os.path.join(folder, f"{name_no_ext}.png")
        img.save(target_path, format="PNG", optimize=True, compress_level=9)
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        target_path = os.path.join(folder, f"{name_no_ext}.jpg")
        img.save(target_path, format="JPEG", quality=jpg_quality, optimize=True, progressive=True)
    if os.path.normpath(target_path) != os.path.normpath(abs_path):
        try:
            os.remove(abs_path)
        except Exception:
            pass
    return target_path

def save_image(file_storage, subdir):
    """Save under uploads/subdir, then auto-compress. Handles files with/without extension."""
    if not (file_storage and (file_storage.filename or "").strip()):
        return None
    uploads_root = app.config["UPLOAD_FOLDER"]
    folder = os.path.join(uploads_root, subdir)
    os.makedirs(folder, exist_ok=True)
    orig = secure_filename(file_storage.filename or "image")
    base = os.path.splitext(orig)[0] or "image"
    unique = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    temp_path = os.path.join(folder, f"{base}-{unique}.tmp")
    file_storage.save(temp_path)
    final_abs = compress_image_inplace(temp_path, max_img_long, jpg_quality)
    uploads_root_abs = os.path.abspath(uploads_root)
    final_abs_norm = os.path.abspath(final_abs)
    rel = os.path.relpath(final_abs_norm, uploads_root_abs)
    return rel.replace("\\", "/")

db = SQLAlchemy(app)

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

class DcLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.String(64), nullable=False, index=True)
    image_path = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # reward status
    is_granted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    granted_by = db.Column(db.String(64), nullable=True)
    granted_at = db.Column(db.DateTime, nullable=True)

@app.errorhandler(RequestEntityTooLarge)
def file_too_large(e):
    flash(f"檔案總大小超過限制：{max_mb} MB。請減少檔案大小或數量。", "error")
    return redirect(request.referrer or url_for("index"))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    game_id = request.form.get("game_id", "").strip()
    notes = request.form.get("notes", "").strip()
    prereg_1 = request.files.get("prereg_1")
    prereg_2 = request.files.get("prereg_2")
    discord_1 = request.files.get("discord_1")
    discord_2 = request.files.get("discord_2")
    # Discord 點讚（>=2）
    dc_like_files = request.files.getlist("dc_like_images")

    if not game_id:
        flash("請輸入『遊戲 ID』（必填）。", "error")
        return redirect(url_for("index"))

    required = [("事前預約(1)", prereg_1), ("事前預約(2)", prereg_2),
                ("Discord 推廣(1)", discord_1), ("Discord 推廣(2)", discord_2)]
    for label, f in required:
        if f is None or f.filename == "":
            flash(f"請上傳『{label}』圖片。", "error")
            return redirect(url_for("index"))
        if not allowed_file(f.filename, getattr(f, 'mimetype', '')):
            flash(f"『{label}』檔案格式不支援。", "error")
            return redirect(url_for("index"))

    like_valid = [f for f in (dc_like_files or []) if f and f.filename]
    if len(like_valid) < 2:
        flash("請上傳至少 2 張『Discord 點讚』截圖。", "error")
        return redirect(url_for("index"))
    for f in like_valid:
        if not allowed_file(f.filename, getattr(f, 'mimetype', '')):
            flash("『Discord 點讚』檔案格式不支援，請僅上傳圖片檔。", "error")
            return redirect(url_for("index"))

    # Save files
    p1 = save_image(prereg_1, "prereg")
    p2 = save_image(prereg_2, "prereg")
    d1 = save_image(discord_1, "discord")
    d2 = save_image(discord_2, "discord")

    sub = Submission(game_id=game_id, prereg_1=p1, prereg_2=p2, discord_1=d1, discord_2=d2, notes=notes)
    db.session.add(sub)
    db.session.commit()

    # Save DcLikes
    for f in like_valid:
        rel = save_image(f, "dc_likes")
        db.session.add(DcLike(game_id=game_id, image_path=rel, notes=notes))
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

    saved_any = False
    for f in files:
        if f and f.filename != "":
            if not allowed_file(f.filename, getattr(f, 'mimetype', '')):
                flash("部分『每日推文』檔案格式不支援，請僅上傳圖片檔。", "error")
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

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

# --- GM (Admin) ---
@app.route("/gm/login", methods=["GET", "POST"])
def gm_login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        GM_ACCOUNTS = {
            os.getenv("ADMIN1_USERNAME", "gm1"): os.getenv("ADMIN1_PASSWORD", "gm1password"),
            os.getenv("ADMIN2_USERNAME", "gm2"): os.getenv("ADMIN2_PASSWORD", "gm2password")
        }
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
    return "gm_user" in session

# toggle granted
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
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

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
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

@app.route("/gm/mark/dclike/<int:lid>")
def gm_mark_dclike(lid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    r = DcLike.query.get_or_404(lid)
    r.is_granted = not r.is_granted
    r.granted_by = session.get("gm_user")
    r.granted_at = datetime.utcnow()
    db.session.commit()
    flash(f"已切換 Discord 點讚 #{lid} 的發放狀態為：{'已發放' if r.is_granted else '未發放'}", "info")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

# batch mark
@app.route("/gm/batch_mark", methods=["POST"])
def gm_batch_mark():
    if not require_gm():
        return redirect(url_for("gm_login"))
    ids = request.form.getlist("ids")
    table = request.form.get("table")
    changed = 0
    if ids:
        if table == "submission":
            for sid in ids:
                s = Submission.query.get(int(sid))
                if s and not s.is_granted:
                    s.is_granted = True; s.granted_by = session.get("gm_user"); s.granted_at = datetime.utcnow(); changed += 1
        elif table == "tweet":
            for tid in ids:
                t = DailyTweet.query.get(int(tid))
                if t and not t.is_granted:
                    t.is_granted = True; t.granted_by = session.get("gm_user"); t.granted_at = datetime.utcnow(); changed += 1
        elif table == "dclike":
            for lid in ids:
                r = DcLike.query.get(int(lid))
                if r and not r.is_granted:
                    r.is_granted = True; r.granted_by = session.get("gm_user"); r.granted_at = datetime.utcnow(); changed += 1
        db.session.commit()
        flash(f"已批次標註 {changed} 筆為已發放", "info")
    else:
        flash("未選取任何項目。", "error")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

# delete routes
@app.route("/gm/delete/sub/<int:sid>")
def gm_delete_sub(sid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    r = Submission.query.get_or_404(sid)
    for path in [r.prereg_1, r.prereg_2, r.discord_1, r.discord_2]:
        if path:
            try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], path))
            except: pass
    db.session.delete(r)
    db.session.commit()
    flash(f"Submission #{sid} 已刪除", "info")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

@app.route("/gm/delete/tweet/<int:tid>")
def gm_delete_tweet(tid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    r = DailyTweet.query.get_or_404(tid)
    if r.image_path:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], r.image_path))
        except: pass
    db.session.delete(r)
    db.session.commit()
    flash(f"DailyTweet #{tid} 已刪除", "info")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

@app.route("/gm/delete/dclike/<int:lid>")
def gm_delete_dclike(lid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    r = DcLike.query.get_or_404(lid)
    if r.image_path:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], r.image_path))
        except: pass
    db.session.delete(r)
    db.session.commit()
    flash(f"DcLike #{lid} 已刪除", "info")
    return redirect(url_for("gm_dashboard", q=request.args.get("q",""), start=request.args.get("start",""), end=request.args.get("end",""), status=request.args.get("status","")))

@app.route("/gm")
def gm_dashboard():
    if not require_gm():
        return redirect(url_for("gm_login"))
    q = request.args.get("q","").strip()
    start = request.args.get("start","").strip()
    end = request.args.get("end","").strip()
    status_filter = request.args.get("status","").strip()

    subs = Submission.query
    tweets = DailyTweet.query
    likes = DcLike.query

    if q:
        subs = subs.filter(Submission.game_id.like(f"%{q}%"))
        tweets = tweets.filter(DailyTweet.game_id.like(f"%{q}%"))
        likes = likes.filter(DcLike.game_id.like(f"%{q}%"))

    def parse_date(s):
        try: return datetime.strptime(s, "%Y-%m-%d")
        except: return None
    start_dt = parse_date(start); end_dt = parse_date(end)
    if start_dt:
        subs = subs.filter(Submission.created_at >= start_dt)
        tweets = tweets.filter(DailyTweet.created_at >= start_dt)
        likes = likes.filter(DcLike.created_at >= start_dt)
    if end_dt:
        eod = end_dt.replace(hour=23, minute=59, second=59)
        subs = subs.filter(Submission.created_at <= eod)
        tweets = tweets.filter(DailyTweet.created_at <= eod)
        likes = likes.filter(DcLike.created_at <= eod)

    if status_filter == "granted":
        subs = subs.filter(Submission.is_granted == True)
        tweets = tweets.filter(DailyTweet.is_granted == True)
        likes = likes.filter(DcLike.is_granted == True)
    elif status_filter == "pending":
        subs = subs.filter(Submission.is_granted == False)
        tweets = tweets.filter(DailyTweet.is_granted == False)
        likes = likes.filter(DcLike.is_granted == False)

    subs = subs.order_by(Submission.created_at.desc()).all()
    tweets = tweets.order_by(DailyTweet.created_at.desc()).all()
    likes = likes.order_by(DcLike.created_at.desc()).all()

    return render_template("admin_dashboard.html", subs=subs, tweets=tweets, likes=likes, q=q, start=start, end=end, status=status_filter)

@app.route("/gm/submission/<int:sid>")
def gm_view_submission(sid):
    if not require_gm():
        return redirect(url_for("gm_login"))
    sub = Submission.query.get_or_404(sid)
    return render_template("view_submission.html", sub=sub)

# Initialize storage & DB
with app.app_context():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
