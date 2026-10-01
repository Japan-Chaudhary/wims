"""
models/user.py
--------------
User helpers for MongoDB.

Collection: 'users'
Document shape:
    {
        _id:           ObjectId,
        username:      str  (unique),
        email:         str  (unique),
        password_hash: str,
        role:          str  ('admin' | 'staff'),
        created_at:    datetime
    }
"""

from datetime import datetime, timezone
from bson import ObjectId
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from database import mongo
from utils import to_ist


class User(UserMixin):
    """Flask-Login compatible user object backed by a MongoDB document."""

    def __init__(self, doc):
        self._doc = doc

    # ---- Flask-Login interface ----
    def get_id(self):
        return str(self._doc['_id'])

    # ---- Field accessors ----
    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def username(self):
        return self._doc.get('username', '')

    @property
    def email(self):
        return self._doc.get('email', '')

    @property
    def password_hash(self):
        return self._doc.get('password_hash', '')

    @property
    def role(self):
        return self._doc.get('role', 'staff')

    @property
    def created_at(self):
        return to_ist(self._doc.get('created_at'))

    # ---- Helpers ----
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username}>'

    # ---- Class-level DB operations ----
    @classmethod
    def _col(cls):
        return mongo.db.users

    @classmethod
    def get_by_id(cls, user_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(user_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def get_by_username(cls, username):
        doc = cls._col().find_one({'username': username})
        return cls(doc) if doc else None

    @classmethod
    def get_by_email(cls, email):
        doc = cls._col().find_one({'email': email})
        return cls(doc) if doc else None

    @classmethod
    def count(cls):
        return cls._col().count_documents({})

    @classmethod
    def create(cls, username, email, password, role='staff'):
        doc = {
            'username': username,
            'email': email,
            'password_hash': generate_password_hash(password),
            'role': role,
            'created_at': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)
