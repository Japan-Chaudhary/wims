"""
routes/__init__.py
------------------
Blueprint registration helper.

Centralizes all blueprint imports so app.py only needs to call
register_blueprints(app) instead of importing each blueprint individually.
"""

from routes.auth import auth_bp
from routes.main import main_bp
from routes.products import products_bp
from routes.warehouses import warehouses_bp
from routes.inventory import inventory_bp
from routes.reports import reports_bp


def register_blueprints(app):
    """Register all blueprints with the Flask application."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(warehouses_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(reports_bp)
