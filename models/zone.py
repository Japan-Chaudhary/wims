"""
models/zone.py
--------------
Zone helpers for MongoDB.

Collection: 'zones'
Document shape:
    {
        _id:               ObjectId,
        name:              str,
        code:              str,
        warehouse_id:      str,
        max_capacity:      float,
        used_capacity:     float,
        reserved_capacity: float,
        capacity_unit:     str,  # 'KG', 'Litres', 'Pieces', 'Boxes', 'Pallets', 'Cubic meters'
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


class Zone:
    def __init__(self, doc):
        self._doc = doc

    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def name(self):
        return self._doc.get('name', '')

    @property
    def code(self):
        return self._doc.get('code', '')

    @property
    def warehouse_id(self):
        return str(self._doc.get('warehouse_id', ''))

    @property
    def max_capacity(self):
        return float(self._doc.get('max_capacity', 0.0))

    @property
    def used_capacity(self):
        return float(self._doc.get('used_capacity', 0.0))

    @property
    def reserved_capacity(self):
        return float(self._doc.get('reserved_capacity', 0.0))

    @property
    def available_capacity(self):
        return max(0.0, self.max_capacity - (self.used_capacity + self.reserved_capacity))

    @property
    def capacity_unit(self):
        return self._doc.get('capacity_unit', 'Pieces')

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
        return f'<Zone {self.code} - {self.name}>'

    @classmethod
    def _col(cls):
        return mongo.db.zones

    @classmethod
    def get_by_id(cls, zone_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(zone_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def find_by_warehouse(cls, warehouse_id):
        cursor = cls._col().find({'warehouse_id': str(warehouse_id), 'is_active': True}).sort('code', 1)
        return [cls(d) for d in cursor]

    @classmethod
    def find_active(cls, search=None):
        filt = {'is_active': True}
        if search:
            pat = re.compile(re.escape(search), re.IGNORECASE)
            filt['$or'] = [{'name': pat}, {'code': pat}, {'description': pat}]
        cursor = cls._col().find(filt).sort('name', 1)
        return [cls(d) for d in cursor]

    @classmethod
    def create(cls, name, code, warehouse_id, max_capacity=0.0, capacity_unit='Pieces', description=None):
        doc = {
            'name': name,
            'code': code.upper(),
            'warehouse_id': str(warehouse_id),
            'max_capacity': float(max_capacity),
            'used_capacity': 0.0,
            'reserved_capacity': 0.0,
            'capacity_unit': capacity_unit if capacity_unit in CAPACITY_UNITS else 'Pieces',
            'description': description,
            'is_active': True,
            'created_at': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)

    def update(self, **fields):
        if 'max_capacity' in fields:
            fields['max_capacity'] = float(fields['max_capacity'])
        if 'code' in fields:
            fields['code'] = fields['code'].upper()
        self._col().update_one({'_id': self._doc['_id']}, {'$set': fields})
        self._doc.update(fields)

    def soft_delete(self):
        self.update(is_active=False)
