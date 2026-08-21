"""
database/__init__.py
--------------------
Creates the shared PyMongo instance used by all routes and models.

Usage:
    from database import mongo

The actual connection is initialized in app.py via mongo.init_app(app).
"""

from flask_pymongo import PyMongo

# Shared PyMongo instance — initialized with the Flask app later
mongo = PyMongo()
