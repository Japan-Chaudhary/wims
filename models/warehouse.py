"""
models/warehouse.py
-------------------
Warehouse helpers for MongoDB.

Collection: 'warehouses'
Document shape:
    {
        _id:               ObjectId,
        name:              str  (unique),
        location:          str | None,
        capacity:          float,
        capacity_unit:     str,  # 'KG', 'Litres', 'Pieces', 'Boxes', 'Pallets', 'Cubic meters'
        used_capacity:     float,
        reserved_capacity: float,
        description:       str | None,
        is_active:         bool,
        created_at:        datetime
    }
"""

from datetime import datetime, timezone
from bson import ObjectId
from database import mongo
from utils import to_ist
import re

CAPACITY_UNITS = ['KG', 'Litres', 'Pieces', 'Boxes', 'Pallets', 'Cubic meters']


class Warehouse:
    def __init__(self, doc):
        self._doc = doc

    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def name(self):
        return self._doc.get('name', '')

    @property
    def location(self):
        return self._doc.get('location')

    @property
    def capacity(self):
        return float(self._doc.get('capacity', 0.0))

    @property
    def max_capacity(self):
        return float(self._doc.get('capacity', 0.0))

    @property
    def capacity_unit(self):
        return self._doc.get('capacity_unit', 'Pieces')

    @property
    def used_capacity(self):
        return float(self._doc.get('used_capacity', 0.0))

    @property
    def reserved_capacity(self):
        return float(self._doc.get('reserved_capacity', 0.0))

    @property
    def available_capacity(self):
        return max(0.0, self.capacity - (self.used_capacity + self.reserved_capacity))

    @property
    def description(self):
        return self._doc.get('description')

    @property
    def is_active(self):
        return self._doc.get('is_active', True)

    @property
    def created_at(self):
        return to_ist(self._doc.get('created_at'))

    def __repr__(self):
        return f'<Warehouse {self.name}>'

    # ---- Class-level DB operations ----
    @classmethod
    def _col(cls):
        return mongo.db.warehouses

    @classmethod
    def get_by_id(cls, wh_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(wh_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def get_by_name(cls, name):
        doc = cls._col().find_one({'name': name})
        return cls(doc) if doc else None

    @classmethod
    def find_active(cls, search=None):
        filt = {'is_active': True}
        if search:
            pat = re.compile(re.escape(search), re.IGNORECASE)
            filt['$or'] = [{'name': pat}, {'location': pat}, {'description': pat}]
        cursor = cls._col().find(filt).sort('name', 1)
        return [cls(d) for d in cursor]

    @classmethod
    def create(cls, name, location=None, capacity=0, capacity_unit='Pieces', description=None):
        doc = {
            'name': name,
            'location': location,
            'capacity': float(capacity),
            'capacity_unit': capacity_unit if capacity_unit in CAPACITY_UNITS else 'Pieces',
            'used_capacity': 0.0,
            'reserved_capacity': 0.0,
            'description': description,
            'is_active': True,
            'created_at': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)

    def update(self, **fields):
        if 'capacity' in fields:
            fields['capacity'] = float(fields['capacity'])
        self._col().update_one({'_id': self._doc['_id']}, {'$set': fields})
        self._doc.update(fields)

    def soft_delete(self):
        self.update(is_active=False)

