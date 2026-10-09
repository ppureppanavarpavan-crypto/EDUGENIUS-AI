import re
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import User, UserPreference

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        academic_level = request.form.get("academic_level", "").strip()
        if not name or len(name) > 100 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter your name and a valid email address.", "error")
        elif len(password) < 10:
            flash("Use a password with at least 10 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(name=name, email=email, academic_level=academic_level or None)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            db.session.add(UserPreference(user_id=user.id))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Could not create that account. Check whether the email is already in use.", "error")
            else:
                login_user(user)
                flash("Welcome! Start by adding a course to your semester.", "success")
                return redirect(url_for("main.dashboard"))
    return render_template("auth.html", mode="register")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Email or password was not recognized.", "error")
        else:
            login_user(user, remember=request.form.get("remember") == "on")
            next_url = request.args.get("next", "")
            parts = urlsplit(next_url)
            if parts.scheme or parts.netloc or not parts.path.startswith("/") or parts.path.startswith("//"):
                next_url = ""
            return redirect(next_url or url_for("main.dashboard"))
    return render_template("auth.html", mode="login")


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("main.index"))
