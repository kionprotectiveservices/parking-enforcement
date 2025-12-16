import os
from flask import Flask, render_template_string, request, redirect, send_file, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import psycopg2

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_SECRET"

DATABASE_URL = os.environ.get("DATABASE_URL")

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ======================
# DATABASE CONNECTION
# ======================
def get_db():
    return psycopg2.connect(DATABASE_URL)

# ======================
# INITIALIZE DATABASE
# ======================
def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT
            );

            CREATE TABLE IF NOT EXISTS violations (
                id SERIAL PRIMARY KEY,
                plate TEXT,
                state TEXT,
                vehicle TEXT,
                property TEXT,
                warning_count INTEGER,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                status TEXT,
                notes TEXT,
                officer TEXT
            );
            """)
            conn.commit()

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
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            return User(*row) if row else None

# ======================
# LOGIN
# ======================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username=%s", (u,))
                row = cur.fetchone()
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
# DASHBOARD
# ======================
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    record = None
    history = []
    if request.method == "POST":
        plate = request.form["plate"].upper()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM violations
                    WHERE plate=%s
                    ORDER BY last_seen DESC
                """, (plate,))
                history = cur.fetchall()
                record = history[0] if history else None
    return render_template_string(TEMPLATE, record=record, history=history, user=current_user)

# ======================
# LOG VIOLATION
# ======================
@app.route("/log", methods=["POST"])
@login_required
def log_violation():
    plate = request.form["plate"].upper()
    now = datetime.now()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT warning_count FROM violations
                WHERE plate=%s
                ORDER BY last_seen DESC LIMIT 1
            """, (plate,))
            row = cur.fetchone()

            warnings = row[0] + 1 if row else 1
            status = "TOW" if warnings >= 2 else "WARNING"

            cur.execute("""
                INSERT INTO violations
                (plate, state, vehicle, property, warning_count,
                 first_seen, last_seen, status, notes, officer)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
# UI
# ======================
LOGIN = """
<h2>Parking Enforcement Login</h2>
<form method="post">
<input name="username" placeholder="Username" required><br>
<input name="password" type="password" required><br>
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
<b>Status:</b> {{record[8]}}<br>
<b>Warnings:</b> {{record[5]}}<br>
{% if record[8] == 'TOW' %}
<a href="/tow/{{record[1]}}">Download Tow PDF</a>
{% endif %}

<h3>History</h3>
<ul>
{% for h in history %}
<li>{{h[7]}} – {{h[8]}} – Officer: {{h[9]}}</li>
{% endfor %}
</ul>
{% endif %}

<hr>
<h3>Log Violation</h3>
<form action="/log" method="post">
<input name="plate" placeholder="Plate" required><br>
<input name="state" placeholder="State"><br>
<input name="vehicle" placeholder="Vehicle"><br>
<input name="property" placeholder="Property"><br>
<textarea name="notes"></textarea><br>
<button>Save</button>
</form>

<a href="/logout">Logout</a>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
