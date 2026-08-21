"""
config.py
---------
Application configuration.

Reads sensitive values from .env file using python-dotenv.
Flask loads this class via app.config.from_object(Config).
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration class for the Flask application."""

    # Secret key for session management and CSRF protection
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-key')

    # MongoDB URI
    MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/wims')
