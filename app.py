
import os
import re
import sqlite3
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"] == "replace_this_with_a_random_secret_key":
    raise RuntimeError("Set a secure SECRET_KEY in your .env file")

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "false").lower() == "true"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)

bcrypt = Bcrypt(app)
csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[]
)

DATABASE = "secure_login.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def initialize_database():
    with app.app_context():
        db = get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            )
        """)
        db.commit()


@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password or not confirm_password:
            flash("All fields are required.", "error")
            return redirect(url_for("register"))

        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must be 3-30 characters and contain only letters, numbers or underscores.", "error")
            return redirect(url_for("register"))

        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "error")
            return redirect(url_for("register"))

        if len(password) < 8 or len(password.encode("utf-8")) > 72:
            flash("Password must be at least 8 characters and no more than 72 bytes.", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, password_hash)
            )
            db.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "error")
            return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Enter your email and password.", "error")
            return redirect(url_for("login"))

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if user and bcrypt.check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session.permanent = True

            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        flash("Please log in to access your dashboard.", "error")
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        username=session.get("username")
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))


@app.errorhandler(429)
def rate_limit_error(error):
    return "Too many login attempts. Please try again later.", 429


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)
