from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, send_from_directory, abort, jsonify
)
from werkzeug.exceptions import HTTPException
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import date, datetime, timedelta
import sqlite3
import calendar
import secrets
import os
import re
import uuid

BASE_DIR = Path(__file__).resolve().parent

# Auto-load .env file if present (no external dependency required, works everywhere)
env_path = BASE_DIR / ".env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

app = Flask(__name__)
app.config["APP_NAME"] = "EduCompanion"

raw_secret = os.environ.get("FLASK_SECRET_KEY")
if not raw_secret:
    raw_secret = secrets.token_hex(32)
    app.logger.warning(
        "FLASK_SECRET_KEY not set in environment; using generated development key. "
        "Set FLASK_SECRET_KEY in production so sessions persist across workers."
    )
app.secret_key = raw_secret

DB_PATH = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "student_companion.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads" / "notes")))

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx",
    "txt", "rtf", "odt", "xls", "xlsx",
    "csv", "png", "jpg", "jpeg"
}

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# Security hardening
is_prod = os.environ.get("FLASK_ENV", "development").lower() == "production"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=is_prod or os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)

if len(app.secret_key) < 32:
    app.logger.warning(
        "FLASK_SECRET_KEY should be at least 32 characters for security."
    )


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT DEFAULT ''
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK(role IN ('admin', 'teacher', 'student')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Check if attendance table exists and has per-user isolation (user_id)
        cols_info = conn.execute("PRAGMA table_info(attendance)").fetchall()
        col_names = [c["name"] for c in cols_info]

        if not col_names:
            conn.execute("""
                CREATE TABLE attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    subject_id INTEGER NOT NULL,
                    class_date TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('Present', 'Absent', 'Cancelled')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(subject_id) REFERENCES subjects(id)
                        ON DELETE CASCADE,
                    UNIQUE(user_id, subject_id, class_date)
                )
            """)
        elif "user_id" not in col_names:
            # Rebuild legacy table to add user_id and update UNIQUE(user_id, subject_id, class_date)
            default_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            fallback_uid = default_user["id"] if default_user else 1
            conn.execute("""
                CREATE TABLE attendance_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    subject_id INTEGER NOT NULL,
                    class_date TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('Present', 'Absent', 'Cancelled')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(subject_id) REFERENCES subjects(id)
                        ON DELETE CASCADE,
                    UNIQUE(user_id, subject_id, class_date)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO attendance_new (id, user_id, subject_id, class_date, status)
                SELECT id, ?, subject_id, class_date, status FROM attendance
            """, (fallback_uid,))
            conn.execute("DROP TABLE attendance")
            conn.execute("ALTER TABLE attendance_new RENAME TO attendance")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                subject_id INTEGER NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                uploaded_by INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(subject_id) REFERENCES subjects(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(uploaded_by) REFERENCES users(id)
            )
        """)


def create_admin(username, password):
    """Create the first admin, or safely reset an existing admin password."""
    username = username.strip()

    if len(username) < 3 or len(password) < 12:
        raise ValueError(
            "Username must have at least 3 characters and "
            "admin password at least 12 characters."
        )

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, role FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        password_hash = generate_password_hash(password)

        if existing:
            if existing["role"] != "admin":
                raise ValueError(
                    "That username already belongs to a non-admin account."
                )
            conn.execute(
                "UPDATE users SET password_hash = ?, active = 1 WHERE id = ?",
                (password_hash, existing["id"])
            )
        else:
            conn.execute("""
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, 'admin')
            """, (username, password_hash))


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, role, active, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

    if not user or not user["active"]:
        session.clear()
        return None

    return user


def get_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "DELETE"):
        if request.path.startswith("/api/"):
            return
        if not app.config.get("WTF_CSRF_ENABLED", True):
            return
        session_token = session.get("_csrf_token")
        form_token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if session_token and form_token and not secrets.compare_digest(session_token, form_token):
            abort(400)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = get_current_user()

            if not user:
                flash("Please log in first.", "warning")
                return redirect(url_for("login", next=request.path))

            if user["role"] not in roles:
                abort(403)

            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_globals():
    return {
        "current_user": get_current_user(),
        "now": datetime.utcnow(),
        "csrf_token": get_csrf_token,
    }


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# ---------------- INPUT VALIDATION HELPERS ----------------

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]{3,40}$")


def validate_username(username):
    """Return an error message string, or None if valid."""
    if not username or not USERNAME_RE.match(username):
        return "Username must be 3-40 letters, numbers, dots, dashes or underscores."
    return None


def validate_password(password, min_len=8):
    """Return an error message string, or None if valid."""
    if not password or len(password) < min_len:
        return f"Password must be at least {min_len} characters."
    return None


def validate_subject_name(name):
    if not name or len(name.strip()) < 1 or len(name) > 100:
        return "Subject name is required and must be under 100 characters."
    return None


def validate_note_title(title):
    if not title or len(title.strip()) < 1 or len(title) > 150:
        return "Title is required and must be under 150 characters."
    return None


def safe_int(value, default=None):
    """Convert to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_iso_date(value, max_future_days=0):
    """Parse an ISO date, optionally bounding future dates."""
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if max_future_days >= 0 and d > date.today() + timedelta(days=max_future_days):
        return None
    return d


def get_period_dates(period, selected_month=None):
    today = date.today()

    if period == "month" and selected_month:
        try:
            year, month = map(int, selected_month.split("-"))
            start = date(year, month, 1)
            end = date(
                year, month,
                calendar.monthrange(year, month)[1]
            )
            return start, end
        except (ValueError, TypeError):
            pass

    if period == "quarter":
        start_month = ((today.month - 1) // 3) * 3 + 1
        end_month = start_month + 2
        start = date(today.year, start_month, 1)
        end = date(
            today.year, end_month,
            calendar.monthrange(today.year, end_month)[1]
        )
    elif period == "semester":
        if today.month <= 6:
            start = date(today.year, 1, 1)
            end = date(today.year, 6, 30)
        else:
            start = date(today.year, 7, 1)
            end = date(today.year, 12, 31)
    else:
        start = today.replace(day=1)
        end = date(
            today.year, today.month,
            calendar.monthrange(today.year, today.month)[1]
        )

    return start, end


# ---------------- AUTHENTICATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        err = validate_username(username)
        pwd_err = validate_password(password)
        if err:
            flash(err, "danger")
        elif pwd_err:
            flash(pwd_err, "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        else:
            try:
                with get_db() as conn:
                    conn.execute("""
                        INSERT INTO users (username, password_hash, role)
                        VALUES (?, ?, 'student')
                    """, (
                        username,
                        generate_password_hash(password)
                    ))
                flash("Student account created. Please log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,)
            ).fetchone()

        if (
            user
            and user["active"]
            and check_password_hash(user["password_hash"], password)
        ):
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]

            destination = request.args.get("next", "") or request.form.get("next", "")
            if destination.startswith("/") and not destination.startswith("//"):
                return redirect(destination)

            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------- ADMIN: TEACHER ACCOUNTS ----------------

@app.route("/admin/teachers", methods=["GET", "POST"])
@roles_required("admin")
def admin_teachers():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        err = validate_username(username)
        pwd_err = validate_password(password)
        if err:
            flash(err, "danger")
        elif pwd_err:
            flash("Teacher password must be at least 8 characters.", "danger")
        else:
            try:
                with get_db() as conn:
                    conn.execute("""
                        INSERT INTO users (username, password_hash, role)
                        VALUES (?, ?, 'teacher')
                    """, (
                        username,
                        generate_password_hash(password)
                    ))
                flash("Teacher account created successfully.", "success")
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "danger")

        return redirect(url_for("admin_teachers"))

    with get_db() as conn:
        teachers = conn.execute("""
            SELECT id, username, active, created_at
            FROM users
            WHERE role = 'teacher'
            ORDER BY username
        """).fetchall()

    return render_template("admin_teachers.html", teachers=teachers)


@app.route("/admin/teachers/<int:user_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_teacher(user_id):
    with get_db() as conn:
        teacher = conn.execute("""
            SELECT id, active FROM users
            WHERE id = ? AND role = 'teacher'
        """, (user_id,)).fetchone()

        if not teacher:
            abort(404)

        conn.execute(
            "UPDATE users SET active = ? WHERE id = ?",
            (0 if teacher["active"] else 1, user_id)
        )

    flash("Teacher account status updated.", "success")
    return redirect(url_for("admin_teachers"))


# ---------------- DASHBOARD & SUBJECTS ----------------

@app.route("/")
@login_required
def dashboard():
    user = get_current_user()
    with get_db() as conn:
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

        note_count = conn.execute(
            "SELECT COUNT(*) AS c FROM notes"
        ).fetchone()["c"]

        attendance_count = conn.execute(
            "SELECT COUNT(*) AS c FROM attendance WHERE user_id = ?",
            (user["id"],)
        ).fetchone()["c"]

    return render_template(
        "dashboard.html",
        subjects=subjects,
        note_count=note_count,
        attendance_count=attendance_count,
    )


@app.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@roles_required("admin", "teacher")
def edit_subject(subject_id):
    with get_db() as conn:
        subject = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()

        if not subject:
            flash("Subject not found.", "danger")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            code = request.form.get("code", "").strip()

            err = validate_subject_name(name)
            if err:
                flash(err, "danger")
                return render_template("edit_subject.html", subject=subject)

            try:
                conn.execute(
                    "UPDATE subjects SET name = ?, code = ? WHERE id = ?",
                    (name, code, subject_id)
                )
                conn.commit()
                flash("Subject updated successfully.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                conn.rollback()
                flash("A subject with that name already exists.", "danger")

        return render_template("edit_subject.html", subject=subject)


@app.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@roles_required("admin", "teacher")
def delete_subject(subject_id):
    with get_db() as conn:
        subject = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()

        if not subject:
            flash("Subject not found.", "danger")
            return redirect(url_for("dashboard"))

        notes_to_delete = conn.execute(
            "SELECT stored_filename FROM notes WHERE subject_id = ?",
            (subject_id,)
        ).fetchall()
        for n in notes_to_delete:
            (UPLOAD_DIR / n["stored_filename"]).unlink(missing_ok=True)

        conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    flash("Subject deleted successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/add-subject", methods=["POST"])
@roles_required("admin", "teacher")
def add_subject():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()

    err = validate_subject_name(name)
    if err:
        flash(err, "danger")
        return redirect(url_for("dashboard"))

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO subjects (name, code) VALUES (?, ?)",
                (name, code)
            )
        flash("Subject added successfully!", "success")
    except sqlite3.IntegrityError:
        flash("This subject already exists.", "danger")

    return redirect(url_for("dashboard"))


# ---------------- USER PROFILE & PASSWORD ----------------

@app.route("/profile")
@login_required
def profile():
    user = get_current_user()
    with get_db() as conn:
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

        if user["role"] == "teacher":
            note_count = conn.execute(
                "SELECT COUNT(*) AS c FROM notes WHERE uploaded_by = ?",
                (user["id"],)
            ).fetchone()["c"]
        else:
            note_count = conn.execute(
                "SELECT COUNT(*) AS c FROM notes"
            ).fetchone()["c"]

    return render_template(
        "profile.html",
        user=user,
        subjects=subjects,
        note_count=note_count,
    )


@app.route("/profile/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = get_current_user()

    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        pwd_err = validate_password(new)
        if pwd_err:
            flash(pwd_err, "danger")
        elif new != confirm:
            flash("Passwords do not match.", "danger")
        else:
            with get_db() as conn:
                db_user = conn.execute(
                    "SELECT password_hash FROM users WHERE id = ?",
                    (user["id"],)
                ).fetchone()

                if not db_user or not check_password_hash(
                    db_user["password_hash"], current
                ):
                    flash("Current password is incorrect.", "danger")
                    return redirect(url_for("change_password"))

                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new), user["id"])
                )

            flash("Password changed successfully. Please log in again.",
                  "success")
            session.clear()
            return redirect(url_for("login"))

    return render_template("change_password.html")


# ---------------- ATTENDANCE TRACKER ----------------

@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    user = get_current_user()
    today = date.today()
    period = request.values.get("period", "month")

    if period not in ("month", "quarter", "semester"):
        period = "month"

    selected_month = request.values.get(
        "month", today.strftime("%Y-%m")
    )

    try:
        year, month_number = map(int, selected_month.split("-"))
        selected_month = date(year, month_number, 1).strftime("%Y-%m")
    except (ValueError, TypeError):
        selected_month = today.strftime("%Y-%m")

    if request.method == "POST":
        subject_id = request.form.get("subject_id", "")
        class_date = request.form.get("class_date", "")
        status = request.form.get("status", "")

        try:
            subject_id = int(subject_id)
            parsed_date = date.fromisoformat(class_date)

            if parsed_date > today:
                raise ValueError("Future date")

            if status not in ("Present", "Absent", "Cancelled"):
                raise ValueError("Invalid status")
        except (ValueError, TypeError):
            flash("Please check the subject, date and status.", "danger")
            return redirect(url_for(
                "attendance", period="month", month=selected_month
            ))

        with get_db() as conn:
            subject = conn.execute(
                "SELECT id FROM subjects WHERE id = ?",
                (subject_id,)
            ).fetchone()

            if not subject:
                flash("Please select a valid subject.", "danger")
                return redirect(url_for("attendance"))

            conn.execute("""
                INSERT INTO attendance (user_id, subject_id, class_date, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, subject_id, class_date)
                DO UPDATE SET status = excluded.status
            """, (user["id"], subject_id, class_date, status))

        flash("Attendance saved successfully!", "success")
        return redirect(url_for(
            "attendance", period="month", month=class_date[:7]
        ))

    start, end = get_period_dates(period, selected_month)

    with get_db() as conn:
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

        report = conn.execute("""
            SELECT
                s.id, s.name, s.code,
                COUNT(CASE WHEN a.status IN
                    ('Present', 'Absent') THEN 1 END) AS total_classes,
                COUNT(CASE WHEN a.status = 'Present'
                    THEN 1 END) AS present_classes,
                COUNT(CASE WHEN a.status = 'Absent'
                    THEN 1 END) AS absent_classes
            FROM subjects s
            LEFT JOIN attendance a
                ON a.subject_id = s.id
                AND a.user_id = ?
                AND a.class_date BETWEEN ? AND ?
            GROUP BY s.id, s.name, s.code
            ORDER BY s.name
        """, (user["id"], start.isoformat(), end.isoformat())).fetchall()

        recent = conn.execute("""
            SELECT a.id, a.class_date, a.status, s.name AS subject_name
            FROM attendance a
            JOIN subjects s ON s.id = a.subject_id
            WHERE a.user_id = ? AND a.class_date BETWEEN ? AND ?
            ORDER BY a.class_date DESC, a.id DESC
        """, (user["id"], start.isoformat(), end.isoformat())).fetchall()

    total = sum(row["total_classes"] for row in report)
    present = sum(row["present_classes"] for row in report)
    overall = round(present * 100 / total, 1) if total else 0

    if start.month == 1:
        previous = date(start.year - 1, 12, 1)
    else:
        previous = date(start.year, start.month - 1, 1)

    if start.month == 12:
        following = date(start.year + 1, 1, 1)
    else:
        following = date(start.year, start.month + 1, 1)

    return render_template(
        "attendance.html",
        subjects=subjects,
        report=report,
        recent=recent,
        period=period,
        start=start.isoformat(),
        end=end.isoformat(),
        today=today.isoformat(),
        selected_month=selected_month,
        previous_month=previous.strftime("%Y-%m"),
        next_month=following.strftime("%Y-%m"),
        total=total,
        present=present,
        overall=overall
    )


# ---------------- CLASS NOTES ----------------

@app.route("/notes")
@login_required
def notes():
    selected_subject = request.args.get("subject", "").strip()

    with get_db() as conn:
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

        query = """
            SELECT n.*, s.name AS subject_name, u.username AS uploader
            FROM notes n
            JOIN subjects s ON s.id = n.subject_id
            JOIN users u ON u.id = n.uploaded_by
        """
        params = []

        if selected_subject:
            try:
                selected_id = int(selected_subject)
            except ValueError:
                abort(400)

            query += " WHERE n.subject_id = ?"
            params.append(selected_id)

        query += " ORDER BY n.uploaded_at DESC, n.id DESC"
        notes_list = conn.execute(query, params).fetchall()

    return render_template(
        "notes.html",
        notes=notes_list,
        subjects=subjects,
        selected_subject=selected_subject
    )


@app.route("/notes/upload", methods=["GET", "POST"])
@roles_required("teacher", "admin")
def upload_note():
    with get_db() as conn:
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        subject_id = request.form.get("subject_id", "").strip()
        file = request.files.get("file")

        err = validate_note_title(title)
        if err:
            flash(err, "danger")
            return redirect(url_for("upload_note"))

        if not file or not file.filename:
            flash("Please select a file.", "danger")
            return redirect(url_for("upload_note"))

        original_name = secure_filename(file.filename)

        if not original_name or not allowed_file(original_name):
            flash("This file type is not allowed.", "danger")
            return redirect(url_for("upload_note"))

        try:
            subject_id = int(subject_id)
        except ValueError:
            flash("Please select a valid subject.", "danger")
            return redirect(url_for("upload_note"))

        with get_db() as conn:
            subject = conn.execute(
                "SELECT id FROM subjects WHERE id = ?",
                (subject_id,)
            ).fetchone()

        if not subject:
            flash("Please select a valid subject.", "danger")
            return redirect(url_for("upload_note"))

        stored_name = uuid.uuid4().hex + "." + original_name.rsplit(".", 1)[1].lower()
        destination = UPLOAD_DIR / stored_name

        try:
            file.save(destination)

            if destination.stat().st_size > MAX_FILE_SIZE:
                destination.unlink(missing_ok=True)
                flash("Maximum file size is 15 MB.", "danger")
                return redirect(url_for("upload_note"))

            with get_db() as conn:
                conn.execute("""
                    INSERT INTO notes (
                        title, description, subject_id,
                        original_filename, stored_filename, uploaded_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    title, description, subject_id,
                    original_name, stored_name, session["user_id"]
                ))

        except Exception:
            destination.unlink(missing_ok=True)
            app.logger.exception("Could not save uploaded note")
            flash("The note could not be saved. Please try again.", "danger")
            return redirect(url_for("upload_note"))

        flash("Class note uploaded successfully.", "success")
        return redirect(url_for("notes"))

    return render_template("upload_note.html", subjects=subjects)


@app.route("/notes/download/<int:note_id>")
@login_required
def download_note(note_id):
    with get_db() as conn:
        note = conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id,)
        ).fetchone()

    if not note:
        abort(404)

    path = UPLOAD_DIR / note["stored_filename"]
    if not path.is_file():
        abort(404)

    return send_from_directory(
        str(UPLOAD_DIR),
        note["stored_filename"],
        as_attachment=True,
        download_name=note["original_filename"]
    )


@app.route("/notes/delete/<int:note_id>", methods=["POST"])
@roles_required("teacher", "admin")
def delete_note(note_id):
    user = get_current_user()

    with get_db() as conn:
        note = conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id,)
        ).fetchone()

        if not note:
            abort(404)

        if user["role"] == "teacher" and note["uploaded_by"] != user["id"]:
            abort(403)

        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    (UPLOAD_DIR / note["stored_filename"]).unlink(missing_ok=True)

    flash("Note deleted successfully.", "success")
    return redirect(url_for("notes"))


# ---------------- JSON REST API (FOR REACT FRONTEND & HEALTHCHECKS) ----------------

@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "app": app.config["APP_NAME"]})


@app.route("/api/summary")
@login_required
def api_summary():
    user = get_current_user()
    with get_db() as conn:
        subjects = [dict(r) for r in conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()]
        notes_rows = [
            dict(r) for r in conn.execute("""
                SELECT n.id, n.title, n.description, n.subject_id, n.original_filename,
                       n.uploaded_at, s.name AS subject_name, u.username AS uploader
                FROM notes n
                JOIN subjects s ON s.id = n.subject_id
                JOIN users u ON u.id = n.uploaded_by
                ORDER BY n.uploaded_at DESC
            """).fetchall()
        ]
        att_rows = [
            dict(r) for r in conn.execute("""
                SELECT a.id, a.subject_id, a.class_date, a.status, s.name AS subject_name
                FROM attendance a
                JOIN subjects s ON s.id = a.subject_id
                WHERE a.user_id = ?
                ORDER BY a.class_date DESC
            """, (user["id"],)).fetchall()
        ]
    return jsonify({
        "user": dict(user),
        "subjects": subjects,
        "notes": notes_rows,
        "attendance": att_rows,
    })


@app.errorhandler(403)
def forbidden(error):
    return render_template(
        "error.html",
        message="You do not have permission to access this page."
    ), 403


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "error.html",
        message="The requested page or file was not found."
    ), 404


@app.errorhandler(400)
def bad_request(error):
    return render_template(
        "error.html",
        message="The request was invalid. Please try again."
    ), 400


@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Internal server error")
    return render_template(
        "error.html",
        message="Something went wrong on our side. Please try again later."
    ), 500


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, HTTPException):
        return error
    app.logger.exception("Unexpected error")
    return render_template(
        "error.html",
        message="An unexpected error occurred. Please try again later."
    ), 500


init_db()

try:
    with get_db() as conn:
        admin_exists = conn.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()

    if not admin_exists:
        admin_user = os.environ.get("ADMIN_USERNAME", "admin")
        admin_pass = os.environ.get(
            "ADMIN_PASSWORD",
            "admin12345678"
        )
        create_admin(admin_user, admin_pass)
        print(f"\n>>> Admin account created: username='{admin_user}'")
        print(">>> Change the password after first login via /profile/change-password\n")
except Exception as e:
    app.logger.warning(f"Could not auto-create admin: {e}")

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", "5000")))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    app.run(host=host, port=port, debug=debug)
