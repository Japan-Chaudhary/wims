"""
routes/main.py
--------------
Main blueprint — dashboard and home page.
"""

from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required
from models.product import Product
from models.warehouse import Warehouse
from models.inventory import Inventory
from models.transaction import InventoryTransaction

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def index():
    return redirect(url_for('main.dashboard'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    # Count active products and warehouses
    total_products = len(Product.find_active())
    total_warehouses = len(Warehouse.find_active())

    # All inventory items
    all_inv = Inventory.find_active()

    # Filter to only those whose product and warehouse are active
    active_products = {p.id for p in Product.find_active()}
    active_warehouses = {w.id for w in Warehouse.find_active()}

    active_inv = [
        inv for inv in all_inv
        if inv.product_id in active_products and inv.warehouse_id in active_warehouses
    ]
    total_inventory = len(active_inv)

    # Total valuation: sum(quantity * unit_price)
    products_map = {p.id: p for p in Product.find_active()}
    total_valuation = sum(
        inv.quantity * products_map[inv.product_id].unit_price
        for inv in active_inv
        if inv.product_id in products_map
    )

    # Low stock count
    low_stock_count = sum(
        1 for inv in active_inv
        if inv.is_low_stock() and inv.min_stock > 0
    )

    # 10 most recent transactions, enriched with product/warehouse/user
    raw_transactions = InventoryTransaction.find_recent(limit=10)
    from models.user import User
    inv_cache = {}
    user_cache = {}
    for txn in raw_transactions:
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
    recent_transactions = raw_transactions

    return render_template(
        'dashboard.html',
        total_products=total_products,
        total_warehouses=total_warehouses,
        total_inventory=total_inventory,
        total_valuation=total_valuation,
        low_stock_count=low_stock_count,
        recent_transactions=recent_transactions
    )
