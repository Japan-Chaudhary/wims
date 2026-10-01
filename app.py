"""
app.py
------
Application entry point using the Flask Application Factory pattern.

Usage:
    python app.py
"""

from flask import Flask, render_template
from flask_login import LoginManager
from config import Config
from database import mongo
from utils import format_currency, format_quantity, format_datetime


def create_app():
    """Create and configure the Flask application."""
    # 1. Create Flask instance
    app = Flask(__name__)

    # 2. Load configuration
    app.config.from_object(Config)

    # 3. Initialize PyMongo
    mongo.init_app(app)

    # 4. Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    # User loader callback — Flask-Login uses this to reload user from session
    @login_manager.user_loader
    def load_user(user_id):
        from models.user import User
        return User.get_by_id(user_id)

    # 5. Register all blueprints
    from routes import register_blueprints
    register_blueprints(app)

    # Register Jinja context filters
    app.jinja_env.filters['currency'] = format_currency
    app.jinja_env.filters['quantity'] = format_quantity
    app.jinja_env.filters['datetime'] = format_datetime

    # 6. Register custom error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('500.html'), 500

    # 7. Ensure indexes and seed admin user
    with app.app_context():
        from models.inventory import Inventory
        Inventory.ensure_indexes()
        _seed_admin_user()

    return app


def _seed_admin_user():
    """Create a default admin user if no users exist."""
    from models.user import User

    if User.count() == 0:
        User.create(
            username='admin',
            email='admin@wims.local',
            password='admin123',
            role='admin'
        )
        print('[OK] Default admin user created (admin / admin123)')


# ---------------------------------------------------------------------------
#  Run the application
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)