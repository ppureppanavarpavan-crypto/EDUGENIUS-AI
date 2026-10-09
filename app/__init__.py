import os

from flask import Flask, render_template

from app.config import get_config
from app.extensions import csrf, db, login_manager


def create_app(config_name=None, test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))
    if test_config:
        app.config.update(test_config)
    if not app.config.get("TESTING") and os.environ.get("FLASK_ENV") == "production":
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError("Set SECRET_KEY before running EduGenius AI in production.")

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User

        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.cli.command("init-db")
    def init_db_command():
        """Create the database tables."""
        with app.app_context():
            db.create_all()
        print("Database tables created.")

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="That page does not exist."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template(
            "error.html", code=413, message="That upload is larger than the 2 MB limit."
        ), 413

    return app
