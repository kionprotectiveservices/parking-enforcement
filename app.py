from flask import Flask, render_template_string, request, redirect, send_file, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import sqlite3, os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_SECRET"

DB = "parking.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ======================
# DATABASE SETUP
# ======================
def init_db():
    with sqlite3.connect(DB) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        );

        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            tow_after INTEGER DEFAULT 2
        );

        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT,
            state TEXT,
            vehicle TEXT,
            property TEXT,
            warning_count INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            status TEXT,
            notes TEXT,
            photo TEXT,
            officer TEXT
        );
        """)

init_db()

# ======================
# USER MODEL
# ======================
class User(UserMixin):
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect(DB) as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return User(*row) if row else None

# ======================
# LOGIN
# ======================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        with sqlite3.connect(DB) as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
            if row and check_password_hash(row[2], p):
                login_user(User(*row))
                return redirect("/")
    return render_template_string(LOGIN)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")

# ======================
# PLATE AUTOCOMPLETE
# ======================
@app.route("/plates")
@login_required
def plates():
    q = request.args.get("q", "").upper()
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            "SELECT DISTINCT plate FROM violations WHERE plate LIKE ?",
            (q + "%",)
        ).fetchall()
    return jsonify([r[0] for r in rows])

# ======================
# DASHBOARD
# ======================
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    record = None
    history = []
    if request.method == "POST":
        plate = request.form["plate"].upper()
        with sqlite3.connect(DB) as conn:
            record = conn.execute(
                "SELECT * FROM violations WHERE plate=? ORDER BY id DESC LIMIT 1",
                (plate,)
            ).fetchone()
            history = conn.execute(
                "SELECT * FROM violations WHERE plate=? ORDER BY last_seen DESC",
                (plate,)
            ).fetchall()
    return render_template_string(TEMPLATE, record=record, history=history, user=current_user)

# ======================
# LOG VIOLATION
# ======================
@app.route("/log", methods=["POST"])
@login_required
def log_violation():
    plate = request.form["plate"].upper()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    photo = request.files.get("photo")
    filename = None

    if photo:
        filename = f"{plate}_{int(datetime.now().timestamp())}.jpg"
        photo.save(os.path.join(UPLOAD_FOLDER, filename))

    with sqlite3.connect(DB) as conn:
        row = conn.execute(
            "SELECT warning_count FROM violations WHERE plate=? ORDER BY id DESC LIMIT 1",
            (plate,)
        ).fetchone()

        warnings = row[0] + 1 if row else 1
        status = "TOW" if warnings >= 2 else "WARNING"

        conn.execute("""
            INSERT INTO violations
            (plate, state, vehicle, property, warning_count, first_seen, last_seen,
             status, notes, photo, officer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plate,
            request.form.get("state"),
            request.form.get("vehicle"),
            request.form.get("property"),
            warnings,
            now if warnings == 1 else None,
            now,
            status,
            request.form.get("notes"),
            filename,
            current_user.username
        ))
        conn.commit()

    return redirect("/")

# ======================
# PDF TOW REPORT
# ======================
@app.route("/tow/<plate>")
@login_required
def tow_report(plate):
    pdf = f"tow_{plate}.pdf"
    doc = SimpleDocTemplate(pdf)
    styles = getSampleStyleSheet()

    content = [
        Paragraph("TOW AUTHORIZATION", styles["Title"]),
        Paragraph(f"Plate: {plate}", styles["Normal"]),
        Paragraph(f"Authorized by: {current_user.username}", styles["Normal"]),
        Paragraph(f"Date: {datetime.now()}", styles["Normal"]),
    ]

    doc.build(content)
    return send_file(pdf, as_attachment=True)

# ======================
# UI TEMPLATES
# ======================
LOGIN = """
<h2>Parking Enforcement Login</h2>
<form method="post">
<input name="username" placeholder="Username" required><br>
<input name="password" type="password" placeholder="Password" required><br>
<button>Login</button>
</form>
"""

TEMPLATE = """
<h1>Parking Enforcement Dashboard</h1>
<p>Logged in as: {{user.username}} ({{user.role}})</p>

<form method="post">
<input name="plate" placeholder="Search Plate" required>
<button>Search</button>
</form>

{% if record %}
<hr>
<b>Status:</b> {{record[7]}}<br>
<b>Warnings:</b> {{record[5]}}<br>
{% if record[7] == 'TOW' %}
<a href="/tow/{{record[1]}}">Download Tow PDF</a>
{% endif %}

<h3>History</h3>
<ul>
{% for h in history %}
<li>{{h[6]}} – {{h[7]}} – Officer: {{h[10]}}</li>
{% endfor %}
</ul>
{% endif %}

<hr>
<h3>Log Violation</h3>
<form action="/log" method="post" enctype="multipart/form-data">
<input name="plate" placeholder="Plate" required><br>
<input name="state" placeholder="State"><br>
<input name="vehicle" placeholder="Vehicle"><br>
<input name="property" placeholder="Property"><br>
<input type="file" name="photo"><br>
<textarea name="notes" placeholder="Notes"></textarea><br>
<button>Save</button>
</form>

<a href="/logout">Logout</a>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
