"""
models/transaction.py
---------------------
InventoryTransaction helpers for MongoDB.

Collection: 'inventory_transactions'
Document shape:
    {
        _id:              ObjectId,
        inventory_id:     str  (Inventory ObjectId as string),
        transaction_type: str  ('stock_in' | 'stock_out'),
        quantity:         int,
        reference:        str | None,
        notes:            str | None,
        performed_by:     str  (User ObjectId as string),
        created_at:       datetime
    }
"""

from datetime import datetime, timezone
from bson import ObjectId
from database import mongo


class InventoryTransaction:
    def __init__(self, doc):
        self._doc = doc
        # Set by routes for template compatibility
        self.inventory = None  # enriched Inventory object
        self.user = None       # enriched User object

    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def inventory_id(self):
        return self._doc.get('inventory_id', '')

    @property
    def transaction_type(self):
        return self._doc.get('transaction_type', '')

    @property
    def quantity(self):
        return self._doc.get('quantity', 0)

    @property
    def reference(self):
        return self._doc.get('reference')

    @property
    def notes(self):
        return self._doc.get('notes')

    @property
    def performed_by(self):
        return self._doc.get('performed_by', '')

    @property
    def created_at(self):
        return self._doc.get('created_at')

    def __repr__(self):
        return f'<Transaction {self.transaction_type} Qty:{self.quantity}>'

    # ---- Class-level DB operations ----
    @classmethod
    def _col(cls):
        return mongo.db.inventory_transactions

    @classmethod
    def create(cls, inventory_id, transaction_type, quantity, performed_by,
               reference=None, notes=None):
        doc = {
            'inventory_id': str(inventory_id),
            'transaction_type': transaction_type,
            'quantity': quantity,
            'reference': reference,
            'notes': notes,
            'performed_by': str(performed_by),
            'created_at': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)

    @classmethod
    def find_recent(cls, limit=10, cutoff=None, type_filter=None, search_ids=None):
        filt = {}
        if cutoff:
            filt['created_at'] = {'$gte': cutoff}
        if type_filter in ('stock_in', 'stock_out'):
            filt['transaction_type'] = type_filter
        if search_ids is not None:
            filt['inventory_id'] = {'$in': search_ids}
        cursor = cls._col().find(filt).sort('created_at', -1).limit(limit)
        return [cls(d) for d in cursor]

    @classmethod
    def find_paginated(cls, page=1, per_page=15, type_filter=None, inventory_ids=None):
        filt = {}
        if type_filter in ('stock_in', 'stock_out'):
            filt['transaction_type'] = type_filter
        if inventory_ids is not None:
            filt['inventory_id'] = {'$in': inventory_ids}
        total = cls._col().count_documents(filt)
        cursor = cls._col().find(filt).sort('created_at', -1)\
            .skip((page - 1) * per_page).limit(per_page)
        items = [cls(d) for d in cursor]
        return items, total

    @classmethod
    def count_all(cls):
        return cls._col().count_documents({})

    @classmethod
    def find_by_inventory_id(cls, inventory_id, cutoff=None):
        filt = {'inventory_id': str(inventory_id)}
        if cutoff:
            filt['created_at'] = {'$gte': cutoff}
        cursor = cls._col().find(filt).sort('created_at', -1)
        return [cls(d) for d in cursor]
