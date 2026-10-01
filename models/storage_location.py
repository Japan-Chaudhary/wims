"""
models/storage_location.py
---------------------------
Storage Location helpers for MongoDB with concurrency-safe capacity management.

Collection: 'storage_locations'
Document shape:
    {
        _id:               ObjectId,
        name:              str,
        code:              str,
        warehouse_id:      str,
        zone_id:           str | None,
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


class StorageLocation:
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
    def zone_id(self):
        return str(self._doc.get('zone_id')) if self._doc.get('zone_id') else None

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
        return f'<StorageLocation {self.code} - {self.name}>'

    @classmethod
    def _col(cls):
        return mongo.db.storage_locations

    @classmethod
    def get_by_id(cls, loc_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(loc_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def get_by_code(cls, code):
        doc = cls._col().find_one({'code': code.upper()})
        return cls(doc) if doc else None

    @classmethod
    def find_by_warehouse(cls, warehouse_id):
        cursor = cls._col().find({'warehouse_id': str(warehouse_id), 'is_active': True}).sort('code', 1)
        return [cls(d) for d in cursor]

    @classmethod
    def find_by_zone(cls, zone_id):
        cursor = cls._col().find({'zone_id': str(zone_id), 'is_active': True}).sort('code', 1)
        return [cls(d) for d in cursor]

    @classmethod
    def find_active(cls, search=None, warehouse_id=None, capacity_unit=None):
        filt = {'is_active': True}
        if warehouse_id:
            filt['warehouse_id'] = str(warehouse_id)
        if capacity_unit:
            filt['capacity_unit'] = capacity_unit
        if search:
            pat = re.compile(re.escape(search), re.IGNORECASE)
            filt['$or'] = [{'name': pat}, {'code': pat}, {'description': pat}]
        cursor = cls._col().find(filt).sort('code', 1)
        return [cls(d) for d in cursor]

    @classmethod
    def create(cls, name, code, warehouse_id, zone_id=None, max_capacity=0.0,
               capacity_unit='Pieces', description=None):
        doc = {
            'name': name,
            'code': code.upper(),
            'warehouse_id': str(warehouse_id),
            'zone_id': str(zone_id) if zone_id else None,
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
        if 'zone_id' in fields and fields['zone_id']:
            fields['zone_id'] = str(fields['zone_id'])
        self._col().update_one({'_id': self._doc['_id']}, {'$set': fields})
        self._doc.update(fields)

    def soft_delete(self):
        self.update(is_active=False)

    # ---- Concurrency-Safe Capacity Operations ----

    def validate_capacity_available(self, required_amount):
        """Check if location currently has at least required_amount available space."""
        return self.available_capacity >= float(required_amount)

    def atomic_add_used_capacity(self, amount):
        """Atomically add used capacity if used + reserved + amount <= max_capacity.

        Returns True on success, False if capacity limit would be exceeded.
        """
        amount = float(amount)
        if amount <= 0:
            return True
        res = self._col().update_one(
            {
                '_id': self._doc['_id'],
                'is_active': True,
                '$expr': {
                    '$lte': [
                        {'$add': ['$used_capacity', '$reserved_capacity', amount]},
                        '$max_capacity'
                    ]
                }
            },
            {'$inc': {'used_capacity': amount}}
        )
        if res.modified_count > 0:
            self._doc['used_capacity'] = self.used_capacity + amount
            return True
        return False

    def atomic_release_used_capacity(self, amount):
        """Atomically release used capacity."""
        amount = float(amount)
        if amount <= 0:
            return True
        res = self._col().update_one(
            {
                '_id': self._doc['_id'],
                'is_active': True,
                'used_capacity': {'$gte': amount}
            },
            {'$inc': {'used_capacity': -amount}}
        )
        if res.modified_count > 0:
            self._doc['used_capacity'] = max(0.0, self.used_capacity - amount)
            return True
        # Fallback to zero out if requested more than recorded
        self._col().update_one({'_id': self._doc['_id']}, {'$set': {'used_capacity': 0.0}})
        self._doc['used_capacity'] = 0.0
        return True

    def atomic_reserve_capacity(self, amount):
        """Atomically reserve capacity if used + reserved + amount <= max_capacity.

        Returns True on success, False if capacity limit would be exceeded.
        """
        amount = float(amount)
        if amount <= 0:
            return True
        res = self._col().update_one(
            {
                '_id': self._doc['_id'],
                'is_active': True,
                '$expr': {
                    '$lte': [
                        {'$add': ['$used_capacity', '$reserved_capacity', amount]},
                        '$max_capacity'
                    ]
                }
            },
            {'$inc': {'reserved_capacity': amount}}
        )
        if res.modified_count > 0:
            self._doc['reserved_capacity'] = self.reserved_capacity + amount
            return True
        return False

    def atomic_cancel_reservation(self, amount):
        """Atomically cancel reserved capacity."""
        amount = float(amount)
        if amount <= 0:
            return True
        res = self._col().update_one(
            {
                '_id': self._doc['_id'],
                'is_active': True,
                'reserved_capacity': {'$gte': amount}
            },
            {'$inc': {'reserved_capacity': -amount}}
        )
        if res.modified_count > 0:
            self._doc['reserved_capacity'] = max(0.0, self.reserved_capacity - amount)
            return True
        self._col().update_one({'_id': self._doc['_id']}, {'$set': {'reserved_capacity': 0.0}})
        self._doc['reserved_capacity'] = 0.0
        return True

    def atomic_confirm_reservation(self, amount):
        """Atomically convert reserved capacity into used capacity."""
        amount = float(amount)
        if amount <= 0:
            return True
        res = self._col().update_one(
            {
                '_id': self._doc['_id'],
                'is_active': True,
                'reserved_capacity': {'$gte': amount}
            },
            {
                '$inc': {
                    'reserved_capacity': -amount,
                    'used_capacity': amount
                }
            }
        )
        if res.modified_count > 0:
            self._doc['reserved_capacity'] = max(0.0, self.reserved_capacity - amount)
            self._doc['used_capacity'] = self.used_capacity + amount
            return True
        return False
