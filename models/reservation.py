"""
models/reservation.py
--------------------
Storage Capacity Reservation helpers for MongoDB.

Collection: 'capacity_reservations'
Document shape:
    {
        _id:                 ObjectId,
        storage_location_id: str,
        warehouse_id:        str,
        product_id:          str | None,
        quantity:            int,
        reserved_capacity:   float,
        capacity_unit:       str,
        status:              str,  # 'active' | 'confirmed' | 'cancelled'
        notes:               str | None,
        performed_by:        str,  # User ObjectId as string
        created_at:          datetime
    }
"""

from datetime import datetime, timezone
from bson import ObjectId
from database import mongo
from utils import to_ist


class CapacityReservation:
    def __init__(self, doc):
        self._doc = doc
        # Set by routes after enrichment
        self.storage_location = None
        self.warehouse = None
        self.product = None
        self.user = None

    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def storage_location_id(self):
        return str(self._doc.get('storage_location_id', ''))

    @property
    def warehouse_id(self):
        return str(self._doc.get('warehouse_id', ''))

    @property
    def product_id(self):
        return str(self._doc.get('product_id')) if self._doc.get('product_id') else None

    @property
    def quantity(self):
        return int(self._doc.get('quantity', 0))

    @property
    def reserved_capacity(self):
        return float(self._doc.get('reserved_capacity', 0.0))

    @property
    def capacity_unit(self):
        return self._doc.get('capacity_unit', 'Pieces')

    @property
    def status(self):
        return self._doc.get('status', 'active')

    @property
    def notes(self):
        return self._doc.get('notes')

    @property
    def performed_by(self):
        return str(self._doc.get('performed_by', ''))

    @property
    def created_at(self):
        return to_ist(self._doc.get('created_at'))

    def __repr__(self):
        return f'<CapacityReservation {self.id} Status:{self.status} Cap:{self.reserved_capacity} {self.capacity_unit}>'

    @classmethod
    def _col(cls):
        return mongo.db.capacity_reservations

    @classmethod
    def get_by_id(cls, res_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(res_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def find_active(cls, storage_location_id=None):
        filt = {'status': 'active'}
        if storage_location_id:
            filt['storage_location_id'] = str(storage_location_id)
        cursor = cls._col().find(filt).sort('created_at', -1)
        return [cls(d) for d in cursor]

    @classmethod
    def find_all(cls, limit=50):
        cursor = cls._col().find().sort('created_at', -1).limit(limit)
        return [cls(d) for d in cursor]

    @classmethod
    def create(cls, storage_location_id, warehouse_id, reserved_capacity,
               capacity_unit='Pieces', product_id=None, quantity=0,
               performed_by='', notes=None):
        doc = {
            'storage_location_id': str(storage_location_id),
            'warehouse_id': str(warehouse_id),
            'product_id': str(product_id) if product_id else None,
            'quantity': int(quantity),
            'reserved_capacity': float(reserved_capacity),
            'capacity_unit': capacity_unit,
            'status': 'active',
            'notes': notes,
            'performed_by': str(performed_by),
            'created_at': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)

    def update_status(self, new_status):
        self._col().update_one({'_id': self._doc['_id']}, {'$set': {'status': new_status}})
        self._doc['status'] = new_status
