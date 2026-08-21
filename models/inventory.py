"""
models/inventory.py
-------------------
Inventory helpers for MongoDB.

Collection: 'inventory'
Document shape:
    {
        _id:          ObjectId,
        warehouse_id: str  (Warehouse ObjectId as string),
        product_id:   str  (Product ObjectId as string),
        quantity:     int,
        min_stock:    int,
        max_stock:    int,
        last_updated: datetime
    }

Unique index on (warehouse_id, product_id) must be created at startup.

Note: .product and .warehouse are set by routes for template compatibility.
"""

from datetime import datetime, timezone
from bson import ObjectId
from database import mongo


class Inventory:
    def __init__(self, doc):
        self._doc = doc
        # Set by routes after enrichment — allows templates to use inv.product / inv.warehouse
        self.product = None
        self.warehouse = None

    @property
    def id(self):
        return str(self._doc['_id'])

    @property
    def warehouse_id(self):
        return self._doc.get('warehouse_id', '')

    @property
    def product_id(self):
        return self._doc.get('product_id', '')

    @property
    def quantity(self):
        return self._doc.get('quantity', 0)

    @property
    def min_stock(self):
        return self._doc.get('min_stock', 0)

    @property
    def max_stock(self):
        return self._doc.get('max_stock', 0)

    @property
    def last_updated(self):
        return self._doc.get('last_updated')

    def is_low_stock(self):
        return self.quantity <= self.min_stock

    def would_exceed_max(self, add_qty):
        """Return True if adding add_qty would exceed max_stock (when max_stock > 0)."""
        return self.max_stock > 0 and (self.quantity + add_qty) > self.max_stock

    def __repr__(self):
        return f'<Inventory W:{self.warehouse_id} P:{self.product_id} Qty:{self.quantity}>'

    # ---- Class-level DB operations ----
    @classmethod
    def _col(cls):
        return mongo.db.inventory

    @classmethod
    def ensure_indexes(cls):
        """Call once at app startup to create the unique compound index."""
        cls._col().create_index(
            [('warehouse_id', 1), ('product_id', 1)],
            unique=True,
            name='uq_warehouse_product'
        )

    @classmethod
    def get_by_id(cls, inv_id):
        try:
            doc = cls._col().find_one({'_id': ObjectId(inv_id)})
        except Exception:
            return None
        return cls(doc) if doc else None

    @classmethod
    def get_by_warehouse_product(cls, warehouse_id, product_id):
        doc = cls._col().find_one({'warehouse_id': str(warehouse_id), 'product_id': str(product_id)})
        return cls(doc) if doc else None

    @classmethod
    def find_active(cls, warehouse_id=None):
        """Return inventory docs joined with active products/warehouses."""
        filt = {}
        if warehouse_id:
            filt['warehouse_id'] = str(warehouse_id)
        cursor = cls._col().find(filt)
        return [cls(d) for d in cursor]

    @classmethod
    def count_active(cls):
        return cls._col().count_documents({})

    @classmethod
    def create(cls, warehouse_id, product_id, quantity=0, min_stock=0, max_stock=0):
        doc = {
            'warehouse_id': str(warehouse_id),
            'product_id': str(product_id),
            'quantity': quantity,
            'min_stock': min_stock,
            'max_stock': max_stock,
            'last_updated': datetime.now(timezone.utc)
        }
        result = cls._col().insert_one(doc)
        doc['_id'] = result.inserted_id
        return cls(doc)

    def update(self, **fields):
        fields['last_updated'] = datetime.now(timezone.utc)
        self._col().update_one({'_id': self._doc['_id']}, {'$set': fields})
        self._doc.update(fields)

    def adjust_quantity(self, delta):
        new_qty = self.quantity + delta
        self.update(quantity=new_qty)
