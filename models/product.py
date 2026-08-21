"""
models/product.py
-----------------
Product helpers for MongoDB.

Collection: 'products'
Document shape:
    {
        _id:         ObjectId,
        name:        str,
        sku:         str  (unique),
        category:    str | None,
        unit_price:  float,
        unit:        str,
        description: str | None,
        is_active:   bool,
        created_at:  datetime
    }
"""

from datetime import datetime, timezone
from bson import ObjectId
from database import mongo
import re


class Product:
    def __init__(self, doc):
        self._doc = doc

    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def name(self):
        return self._doc.get('name', '')

    @property
    def sku(self):
        return self._doc.get('sku', '')

    @property
    def category(self):
        return self._doc.get('category')

    @property
    def unit_price(self):
        return self._doc.get('unit_price', 0.0)

    @property
    def unit(self):
        return self._doc.get('unit', 'pcs')

    @property
    def description(self):
        return self._doc.get('description')

    @property
    def is_active(self):
        return self._doc.get('is_active', True)

    @property
    def created_at(self):
        return self._doc.get('created_at')

    def __repr__(self):
        return f'<Product {self.sku} - {self.name}>'

    # ---- Class-level DB operations ----
    @classmethod
    def _col(cls):
        return mongo.db.products

    @classmethod
    def get_by_id(cls, product_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(product_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def get_by_sku(cls, sku):
        doc = cls._col().find_one({'sku': sku})
        return cls(doc) if doc else None

    @classmethod
    def find_active(cls, search=None, category=None, sort_by='created_at', sort_dir=-1):
        filt = {'is_active': True}
        if category:
            filt['category'] = category
        if search:
            pat = re.compile(re.escape(search), re.IGNORECASE)
            filt['$or'] = [{'name': pat}, {'sku': pat}, {'description': pat}]
        cursor = cls._col().find(filt).sort(sort_by, sort_dir)
        return [cls(d) for d in cursor]

    @classmethod
    def distinct_categories(cls):
        return [c for c in cls._col().distinct('category', {'is_active': True, 'category': {'$nin': [None, '']}}) if c]

    @classmethod
    def create(cls, name, sku, category=None, unit_price=0.0, unit='pcs', description=None):
        doc = {
            'name': name,
            'sku': sku,
            'category': category,
            'unit_price': unit_price,
            'unit': unit,
            'description': description,
            'is_active': True,
            'created_at': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)

    def update(self, **fields):
        self._col().update_one({'_id': self._doc['_id']}, {'$set': fields})
        self._doc.update(fields)

    def soft_delete(self):
        self.update(is_active=False)
