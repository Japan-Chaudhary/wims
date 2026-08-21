"""
routes/reports.py
-----------------
Reports blueprint — inventory valuation, low stock, and movement reports.
"""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request
from flask_login import login_required
from models.product import Product
from models.warehouse import Warehouse
from models.inventory import Inventory
from models.transaction import InventoryTransaction

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/')
@login_required
def index():
    products_map = {p.id: p for p in Product.find_active()}
    warehouses_map = {w.id: w for w in Warehouse.find_active()}
    all_inv = Inventory.find_active()

    active_inv = [
        inv for inv in all_inv
        if inv.product_id in products_map and inv.warehouse_id in warehouses_map
    ]

    total_val_query = sum(
        inv.quantity * products_map[inv.product_id].unit_price
        for inv in active_inv
    )
    low_stock_count = sum(1 for inv in active_inv if inv.is_low_stock() and inv.min_stock > 0)
    total_movements = InventoryTransaction.count_all()

    return render_template(
        'reports/index.html',
        total_valuation=total_val_query,
        low_stock_count=low_stock_count,
        total_movements=total_movements
    )


@reports_bp.route('/inventory-value')
@login_required
def inventory_value():
    warehouse_filter = request.args.get('warehouse_id', '', type=str).strip()

    products_map = {p.id: p for p in Product.find_active()}
    warehouses_map = {w.id: w for w in Warehouse.find_active()}

    all_inv = Inventory.find_active(warehouse_id=warehouse_filter or None)

    valuation_items = []
    total_system_value = 0.0
    total_units = 0

    for inv in all_inv:
        prod = products_map.get(inv.product_id)
        wh = warehouses_map.get(inv.warehouse_id)
        if not prod or not wh:
            continue
        item_value = inv.quantity * prod.unit_price
        total_system_value += item_value
        total_units += inv.quantity
        valuation_items.append({
            'inventory_id': inv.id,
            'product_name': prod.name,
            'sku': prod.sku,
            'category': prod.category,
            'unit': prod.unit,
            'unit_price': prod.unit_price,
            'warehouse_name': wh.name,
            'quantity': inv.quantity,
            'total_value': item_value
        })

    valuation_items.sort(key=lambda x: (x['warehouse_name'], x['product_name']))
    warehouses = list(warehouses_map.values())
    warehouses.sort(key=lambda w: w.name)

    return render_template(
        'reports/inventory_value.html',
        items=valuation_items,
        total_system_value=total_system_value,
        total_units=total_units,
        warehouses=warehouses,
        warehouse_filter=warehouse_filter
    )


@reports_bp.route('/low-stock')
@login_required
def low_stock():
    products_map = {p.id: p for p in Product.find_active()}
    warehouses_map = {w.id: w for w in Warehouse.find_active()}
    all_inv = Inventory.find_active()

    reorder_list = []
    for inv in all_inv:
        prod = products_map.get(inv.product_id)
        wh = warehouses_map.get(inv.warehouse_id)
        if not prod or not wh:
            continue
        if not (inv.quantity <= inv.min_stock and inv.min_stock > 0):
            continue
        target = inv.max_stock if inv.max_stock > 0 else (inv.min_stock * 2)
        suggested_reorder = max(target - inv.quantity, 0)
        reorder_list.append({
            'inventory_id': inv.id,
            'product_name': prod.name,
            'sku': prod.sku,
            'unit': prod.unit,
            'warehouse_name': wh.name,
            'quantity': inv.quantity,
            'min_stock': inv.min_stock,
            'max_stock': inv.max_stock,
            'suggested_reorder': suggested_reorder,
            'unit_price': prod.unit_price,
            'estimated_reorder_cost': suggested_reorder * prod.unit_price
        })

    reorder_list.sort(key=lambda x: (x['warehouse_name'], x['product_name']))
    total_reorder_cost = sum(item['estimated_reorder_cost'] for item in reorder_list)

    return render_template(
        'reports/low_stock.html',
        items=reorder_list,
        total_reorder_cost=total_reorder_cost
    )


@reports_bp.route('/movement')
@login_required
def stock_movement():
    days = request.args.get('days', 30, type=int)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    transactions = InventoryTransaction.find_recent(limit=0, cutoff=cutoff_date)
    # find_recent with limit=0 means unlimited — fetch all matching cutoff
    # Re-fetch properly:
    from database import mongo
    cursor = mongo.db.inventory_transactions.find(
        {'created_at': {'$gte': cutoff_date}}
    ).sort('created_at', -1)
    transactions = [InventoryTransaction(d) for d in cursor]

    products_map = {p.id: p for p in Product.find_active()}
    warehouses_map = {w.id: w for w in Warehouse.find_active()}
    from models.user import User
    inv_cache = {}
    user_cache = {}

    for txn in transactions:
        if txn.inventory_id not in inv_cache:
            inv = Inventory.get_by_id(txn.inventory_id)
            if inv:
                inv.product = products_map.get(inv.product_id)
                inv.warehouse = warehouses_map.get(inv.warehouse_id)
            inv_cache[txn.inventory_id] = inv
        txn.inventory = inv_cache.get(txn.inventory_id)
        if txn.performed_by not in user_cache:
            user_cache[txn.performed_by] = User.get_by_id(txn.performed_by)
        txn.user = user_cache.get(txn.performed_by)

    total_stock_in_qty = sum(t.quantity for t in transactions if t.transaction_type == 'stock_in')
    total_stock_out_qty = sum(t.quantity for t in transactions if t.transaction_type == 'stock_out')
    total_txns = len(transactions)

    return render_template(
        'reports/movement.html',
        transactions=transactions,
        days=days,
        total_stock_in_qty=total_stock_in_qty,
        total_stock_out_qty=total_stock_out_qty,
        total_txns=total_txns
    )
