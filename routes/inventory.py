"""
routes/inventory.py
-------------------
Inventory Management & Stock Transactions blueprint.

Routes:
    GET         /inventory                    — List all stock levels
    GET/POST    /inventory/add                — Assign product to warehouse inventory
    GET/POST    /inventory/<id>/edit          — Edit min/max stock thresholds
    GET/POST    /inventory/stock-in           — Perform Stock In transaction
    GET/POST    /inventory/stock-out          — Perform Stock Out transaction
    GET         /inventory/transactions       — View full transaction audit log

FIX: max_stock limit is now enforced on both add_inventory (initial quantity)
     and stock_in (adding more units). If max_stock > 0 and the resulting
     quantity would exceed it, the operation is blocked with a clear error.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models.product import Product
from models.warehouse import Warehouse
from models.inventory import Inventory
from models.transaction import InventoryTransaction
from utils import Pagination

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _get_active_products():
    return {p.id: p for p in Product.find_active()}


def _get_active_warehouses():
    return {w.id: w for w in Warehouse.find_active()}


def _enrich_inventory(inv_list, products_map, warehouses_map):
    """Attach product/warehouse objects to inventory items; skip orphans."""
    result = []
    for inv in inv_list:
        prod = products_map.get(inv.product_id)
        wh = warehouses_map.get(inv.warehouse_id)
        if prod and wh:
            inv.product = prod
            inv.warehouse = wh
            result.append(inv)
    return result


# ---------------------------------------------------------------------------
#  LIST INVENTORY
# ---------------------------------------------------------------------------
@inventory_bp.route('/')
@login_required
def list_inventory():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('q', '', type=str).strip().lower()
    warehouse_filter = request.args.get('warehouse_id', '', type=str).strip()
    low_stock_filter = request.args.get('low_stock', '', type=str).strip()

    products_map = _get_active_products()
    warehouses_map = _get_active_warehouses()

    all_inv = Inventory.find_active(warehouse_id=warehouse_filter or None)
    enriched = _enrich_inventory(all_inv, products_map, warehouses_map)

    # Search filter
    if search:
        enriched = [
            inv for inv in enriched
            if search in inv.product.name.lower()
            or search in inv.product.sku.lower()
            or search in inv.warehouse.name.lower()
        ]

    # Low-stock filter
    if low_stock_filter == '1':
        enriched = [inv for inv in enriched if inv.is_low_stock() and inv.min_stock > 0]

    # Sort by warehouse name then product name
    enriched.sort(key=lambda i: (i.warehouse.name, i.product.name))

    total_records = len(enriched)
    low_stock_total = sum(1 for inv in enriched if inv.is_low_stock() and inv.min_stock > 0)

    # Paginate
    start = (page - 1) * per_page
    inventory_items = enriched[start:start + per_page]

    pagination = Pagination(page, per_page, total_records)
    warehouses = list(warehouses_map.values())
    warehouses.sort(key=lambda w: w.name)

    return render_template(
        'inventory/list.html',
        inventory_items=inventory_items,
        pagination=pagination,
        search=search,
        warehouse_filter=warehouse_filter,
        low_stock_filter=low_stock_filter,
        warehouses=warehouses,
        total_records=total_records,
        low_stock_total=low_stock_total
    )


# ---------------------------------------------------------------------------
#  ADD / ASSIGN PRODUCT TO WAREHOUSE INVENTORY
# ---------------------------------------------------------------------------
@inventory_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_inventory():
    """Assign a product to a warehouse with initial quantity and thresholds.

    FIX: Validates that the initial quantity does not exceed max_stock
         when max_stock > 0.
    """
    if request.method == 'POST':
        warehouse_id = request.form.get('warehouse_id', '').strip()
        product_id = request.form.get('product_id', '').strip()
        quantity = request.form.get('quantity', 0, type=int)
        min_stock = request.form.get('min_stock', 0, type=int)
        max_stock = request.form.get('max_stock', 0, type=int)

        errors = []
        if not warehouse_id:
            errors.append('Please select a warehouse.')
        if not product_id:
            errors.append('Please select a product.')
        if quantity < 0:
            errors.append('Initial quantity cannot be negative.')
        if min_stock < 0:
            errors.append('Minimum stock threshold cannot be negative.')
        if max_stock < 0:
            errors.append('Maximum stock threshold cannot be negative.')

        # FIX: Enforce max_stock limit on initial quantity
        if max_stock > 0 and quantity > max_stock:
            errors.append(
                f'Initial quantity ({quantity}) exceeds the maximum stock limit ({max_stock}). '
                f'Please reduce the quantity or increase the max stock limit.'
            )

        # Check for existing inventory entry
        if warehouse_id and product_id and not errors:
            existing = Inventory.get_by_warehouse_product(warehouse_id, product_id)
            if existing:
                product = Product.get_by_id(product_id)
                warehouse = Warehouse.get_by_id(warehouse_id)
                errors.append(
                    f'Product "{product.name}" is already tracked in warehouse '
                    f'"{warehouse.name}". Edit the existing inventory entry instead.'
                )

        if errors:
            for error in errors:
                flash(error, 'danger')
            warehouses = Warehouse.find_active()
            products = Product.find_active()
            return render_template('inventory/form.html', warehouses=warehouses, products=products, mode='add')

        # Create Inventory Record
        inventory = Inventory.create(
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=quantity,
            min_stock=min_stock,
            max_stock=max_stock
        )

        # Log initial Stock In transaction if initial quantity > 0
        if quantity > 0:
            InventoryTransaction.create(
                inventory_id=inventory.id,
                transaction_type='stock_in',
                quantity=quantity,
                performed_by=current_user.id,
                reference='INITIAL_STOCK',
                notes='Initial stock assigned during inventory registration'
            )

        flash('Product inventory assigned to warehouse successfully!', 'success')
        return redirect(url_for('inventory.list_inventory'))

    warehouses = Warehouse.find_active()
    products = Product.find_active()
    return render_template('inventory/form.html', warehouses=warehouses, products=products, mode='add', inventory=None)


# ---------------------------------------------------------------------------
#  EDIT THRESHOLDS
# ---------------------------------------------------------------------------
@inventory_bp.route('/<inventory_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_inventory(inventory_id):
    inventory = Inventory.get_by_id(inventory_id)
    if inventory is None:
        flash('Inventory item not found.', 'warning')
        return redirect(url_for('inventory.list_inventory'))

    # Enrich with product and warehouse for template display
    inventory.product = Product.get_by_id(inventory.product_id)
    inventory.warehouse = Warehouse.get_by_id(inventory.warehouse_id)

    if request.method == 'POST':
        min_stock = request.form.get('min_stock', 0, type=int)
        max_stock = request.form.get('max_stock', 0, type=int)

        errors = []
        if min_stock < 0:
            errors.append('Minimum stock threshold cannot be negative.')
        if max_stock < 0:
            errors.append('Maximum stock threshold cannot be negative.')

        # Warn if current quantity already exceeds new max_stock
        if max_stock > 0 and inventory.quantity > max_stock:
            errors.append(
                f'Current quantity ({inventory.quantity}) already exceeds the new max stock limit ({max_stock}). '
                f'Please set a higher max stock or perform a stock-out first.'
            )

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('inventory/form.html', mode='edit', inventory=inventory)

        inventory.update(min_stock=min_stock, max_stock=max_stock)
        flash('Inventory thresholds updated successfully!', 'success')
        return redirect(url_for('inventory.list_inventory'))

    return render_template('inventory/form.html', mode='edit', inventory=inventory)


# ---------------------------------------------------------------------------
#  STOCK IN — Add stock to inventory
# ---------------------------------------------------------------------------
@inventory_bp.route('/stock-in', methods=['GET', 'POST'])
@login_required
def stock_in():
    """Perform Stock In movement.

    FIX: Checks max_stock limit before adding. If max_stock > 0 and
         (current_quantity + add_qty) > max_stock, the operation is blocked.
    """
    if request.method == 'POST':
        inventory_id = request.form.get('inventory_id', '').strip()
        quantity = request.form.get('quantity', 0, type=int)
        reference = request.form.get('reference', '').strip()
        notes = request.form.get('notes', '').strip()

        errors = []
        if not inventory_id:
            errors.append('Please select an inventory item.')
        if quantity <= 0:
            errors.append('Quantity must be greater than zero.')

        inventory = Inventory.get_by_id(inventory_id) if inventory_id else None
        if inventory_id and not inventory:
            errors.append('Selected inventory record not found.')

        # FIX: Enforce max_stock limit
        if inventory and quantity > 0 and inventory.would_exceed_max(quantity):
            available_space = inventory.max_stock - inventory.quantity
            errors.append(
                f'Cannot add {quantity} units. Max stock limit is {inventory.max_stock}. '
                f'Current stock: {inventory.quantity}. Available space: {available_space} units.'
            )

        if errors:
            for error in errors:
                flash(error, 'danger')
            all_inv = _build_inventory_list()
            return render_template('inventory/stock_in.html', inventory_list=all_inv)

        # Increase stock quantity
        inventory.adjust_quantity(quantity)

        # Log transaction
        InventoryTransaction.create(
            inventory_id=inventory.id,
            transaction_type='stock_in',
            quantity=quantity,
            performed_by=current_user.id,
            reference=reference or None,
            notes=notes or None
        )

        # Attach names for flash message
        prod = Product.get_by_id(inventory.product_id)
        wh = Warehouse.get_by_id(inventory.warehouse_id)
        flash(f'Successfully added {quantity} units to {prod.name} ({wh.name})!', 'success')
        return redirect(url_for('inventory.list_inventory'))

    preselected_id = request.args.get('inventory_id', '', type=str)
    return render_template('inventory/stock_in.html', inventory_list=_build_inventory_list(), preselected_id=preselected_id)


# ---------------------------------------------------------------------------
#  STOCK OUT — Remove stock from inventory
# ---------------------------------------------------------------------------
@inventory_bp.route('/stock-out', methods=['GET', 'POST'])
@login_required
def stock_out():
    if request.method == 'POST':
        inventory_id = request.form.get('inventory_id', '').strip()
        quantity = request.form.get('quantity', 0, type=int)
        reference = request.form.get('reference', '').strip()
        notes = request.form.get('notes', '').strip()

        errors = []
        if not inventory_id:
            errors.append('Please select an inventory item.')
        if quantity <= 0:
            errors.append('Quantity must be greater than zero.')

        inventory = Inventory.get_by_id(inventory_id) if inventory_id else None
        if inventory_id and not inventory:
            errors.append('Selected inventory record not found.')
        elif inventory and quantity > inventory.quantity:
            errors.append(
                f'Insufficient stock! Current stock is {inventory.quantity} units, '
                f'but requested {quantity} units.'
            )

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('inventory/stock_out.html', inventory_list=_build_inventory_list())

        # Decrease stock quantity
        inventory.adjust_quantity(-quantity)

        # Log transaction
        InventoryTransaction.create(
            inventory_id=inventory.id,
            transaction_type='stock_out',
            quantity=quantity,
            performed_by=current_user.id,
            reference=reference or None,
            notes=notes or None
        )

        prod = Product.get_by_id(inventory.product_id)
        wh = Warehouse.get_by_id(inventory.warehouse_id)
        flash(f'Successfully removed {quantity} units from {prod.name} ({wh.name})!', 'success')
        return redirect(url_for('inventory.list_inventory'))

    preselected_id = request.args.get('inventory_id', '', type=str)
    return render_template('inventory/stock_out.html', inventory_list=_build_inventory_list(), preselected_id=preselected_id)


# ---------------------------------------------------------------------------
#  TRANSACTION HISTORY
# ---------------------------------------------------------------------------
@inventory_bp.route('/transactions')
@login_required
def list_transactions():
    page = request.args.get('page', 1, type=int)
    per_page = 15
    type_filter = request.args.get('type', '', type=str).strip()
    search = request.args.get('q', '', type=str).strip().lower()

    products_map = _get_active_products()
    warehouses_map = _get_active_warehouses()

    # If searching, first find matching inventory_ids
    inventory_ids = None
    if search:
        all_inv = Inventory.find_active()
        enriched = _enrich_inventory(all_inv, products_map, warehouses_map)
        inventory_ids = [
            inv.id for inv in enriched
            if search in inv.product.name.lower()
            or search in inv.product.sku.lower()
            or search in inv.warehouse.name.lower()
        ]

    transactions, total = InventoryTransaction.find_paginated(
        page=page, per_page=per_page,
        type_filter=type_filter or None,
        inventory_ids=inventory_ids
    )

    # Enrich transactions with product/warehouse names and user
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

    pagination = Pagination(page, per_page, total)

    return render_template(
        'inventory/transactions.html',
        transactions=transactions,
        pagination=pagination,
        type_filter=type_filter,
        search=search
    )


# ---------------------------------------------------------------------------
#  Internal helper
# ---------------------------------------------------------------------------
def _build_inventory_list():
    """Return enriched inventory items for dropdown lists."""
    products_map = _get_active_products()
    warehouses_map = _get_active_warehouses()
    all_inv = Inventory.find_active()
    return _enrich_inventory(all_inv, products_map, warehouses_map)
