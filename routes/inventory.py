from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models.product import Product
from models.warehouse import Warehouse
from models.inventory import Inventory
from models.transaction import InventoryTransaction
from models.storage_location import StorageLocation
from utils import Pagination, format_datetime

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _get_active_products():
    return {p.id: p for p in Product.find_active()}


def _get_active_warehouses():
    return {w.id: w for w in Warehouse.find_active()}


def _enrich_inventory(inv_list, products_map, warehouses_map):
    """Attach product/warehouse/storage objects to inventory items; skip orphans."""
    result = []
    loc_map = {l.id: l for l in StorageLocation.find_active()}
    for inv in inv_list:
        prod = products_map.get(inv.product_id)
        wh = warehouses_map.get(inv.warehouse_id)
        if prod and wh:
            inv.product = prod
            inv.warehouse = wh
            if inv.storage_location_id:
                inv.storage_location = loc_map.get(inv.storage_location_id)
            result.append(inv)
    return result


# ---------------------------------------------------------------------------
#  SMART STORAGE ALLOCATION ENDPOINT
# ---------------------------------------------------------------------------
@inventory_bp.route('/smart-allocation', methods=['POST'])
@login_required
def smart_allocation():
    """POST /inventory/smart-allocation — Recommend or distribute stock across compatible storage locations."""
    data = request.get_json(silent=True) or request.form
    product_id = data.get('product_id', '').strip()
    quantity = int(data.get('quantity', 0))
    warehouse_id = data.get('warehouse_id', '').strip()

    if not product_id or quantity <= 0:
        return jsonify({'error': 'Valid product_id and quantity > 0 are required.'}), 400

    product = Product.get_by_id(product_id)
    if not product:
        return jsonify({'error': 'Product not found.'}), 404

    capacity_needed = quantity * product.capacity_per_unit
    unit = product.capacity_unit

    # Find candidate locations matching capacity unit and active state
    candidate_locations = StorageLocation.find_active(warehouse_id=warehouse_id or None, capacity_unit=unit)

    # Sort locations by available capacity (descending)
    candidate_locations.sort(key=lambda loc: loc.available_capacity, reverse=True)

    allocations = []
    remaining_quantity = quantity
    remaining_capacity = capacity_needed

    for loc in candidate_locations:
        if remaining_quantity <= 0:
            break
        if loc.available_capacity <= 0:
            continue

        # Determine how much can fit in this location
        fit_units = int(loc.available_capacity // product.capacity_per_unit)
        if fit_units <= 0:
            continue

        alloc_qty = min(remaining_quantity, fit_units)
        alloc_cap = alloc_qty * product.capacity_per_unit

        allocations.append({
            'storage_location_id': loc.id,
            'code': loc.code,
            'name': loc.name,
            'warehouse_id': loc.warehouse_id,
            'allocated_quantity': alloc_qty,
            'allocated_capacity': alloc_cap,
            'available_capacity_after': round(loc.available_capacity - alloc_cap, 2)
        })

        remaining_quantity -= alloc_qty
        remaining_capacity -= alloc_cap

    fully_allocated = (remaining_quantity == 0)

    res_payload = {
        'success': True,
        'product': {
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'capacity_per_unit': product.capacity_per_unit,
            'capacity_unit': product.capacity_unit
        },
        'requested_quantity': quantity,
        'total_capacity_needed': capacity_needed,
        'capacity_unit': unit,
        'fully_allocated': fully_allocated,
        'unallocated_quantity': remaining_quantity,
        'allocations': allocations
    }

    if not fully_allocated:
        res_payload['warning'] = f'Insufficient capacity across compatible locations! {remaining_quantity} units unallocated.'

    return jsonify(res_payload)


# ---------------------------------------------------------------------------
#  CAPACITY ALERTS ENDPOINT
# ---------------------------------------------------------------------------
@inventory_bp.route('/alerts/capacity', methods=['GET'])
@inventory_bp.route('/../alerts/capacity', methods=['GET'])
@login_required
def capacity_alerts():
    """GET /alerts/capacity — Retrieve storage capacity warning alerts."""
    threshold_pct = request.args.get('threshold', 80.0, type=float)

    locations = StorageLocation.find_active()
    warehouses = Warehouse.find_active()

    alerts = []

    # Check Storage Locations
    for loc in locations:
        if loc.max_capacity > 0:
            utilization = round(((loc.used_capacity + loc.reserved_capacity) / loc.max_capacity) * 100, 1)
            if utilization >= threshold_pct:
                severity = 'CRITICAL' if utilization >= 95.0 else 'WARNING'
                alerts.append({
                    'type': 'storage_location',
                    'id': loc.id,
                    'code': loc.code,
                    'name': loc.name,
                    'warehouse_id': loc.warehouse_id,
                    'severity': severity,
                    'utilization_percentage': min(100.0, utilization),
                    'max_capacity': loc.max_capacity,
                    'used_capacity': loc.used_capacity,
                    'reserved_capacity': loc.reserved_capacity,
                    'available_capacity': loc.available_capacity,
                    'capacity_unit': loc.capacity_unit,
                    'message': f'Storage location {loc.code} is at {utilization}% capacity utilization.'
                })

    # Check Warehouses
    for wh in warehouses:
        wh_max = wh.capacity
        wh_used = wh.used_capacity + wh.reserved_capacity
        if wh_max > 0:
            utilization = round((wh_used / wh_max) * 100, 1)
            if utilization >= threshold_pct:
                severity = 'CRITICAL' if utilization >= 95.0 else 'WARNING'
                alerts.append({
                    'type': 'warehouse',
                    'id': wh.id,
                    'name': wh.name,
                    'severity': severity,
                    'utilization_percentage': min(100.0, utilization),
                    'max_capacity': wh_max,
                    'used_capacity': wh.used_capacity,
                    'reserved_capacity': wh.reserved_capacity,
                    'available_capacity': wh.available_capacity,
                    'capacity_unit': wh.capacity_unit,
                    'message': f'Warehouse "{wh.name}" is at {utilization}% capacity utilization.'
                })

    if request.args.get('format') == 'json' or request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({
            'threshold_percentage': threshold_pct,
            'total_alerts': len(alerts),
            'alerts': alerts
        })

    return render_template('inventory/alerts.html', alerts=alerts, threshold_pct=threshold_pct)


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
    """Assign a product to a warehouse with initial quantity and thresholds."""
    if request.method == 'POST':
        warehouse_id = request.form.get('warehouse_id', '').strip()
        product_id = request.form.get('product_id', '').strip()
        storage_location_id = request.form.get('storage_location_id', '').strip() or None
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

        # Enforce max_stock limit on initial quantity
        if max_stock > 0 and quantity > max_stock:
            errors.append(
                f'Initial quantity ({quantity}) exceeds the maximum stock limit ({max_stock}). '
                f'Please reduce the quantity or increase the max stock limit.'
            )

        # Capacity validation if storage location selected
        loc = StorageLocation.get_by_id(storage_location_id) if storage_location_id else None
        product = Product.get_by_id(product_id) if product_id else None
        capacity_needed = 0.0
        if loc and product and quantity > 0:
            capacity_needed = quantity * product.capacity_per_unit
            if not loc.validate_capacity_available(capacity_needed):
                errors.append(
                    f'Insufficient storage location capacity in {loc.code}! '
                    f'Needs {capacity_needed} {loc.capacity_unit}, but available is {loc.available_capacity} {loc.capacity_unit}.'
                )

        # Check for existing inventory entry
        if warehouse_id and product_id and not errors:
            existing = Inventory.get_by_warehouse_product(warehouse_id, product_id, storage_location_id)
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
            storage_locations = StorageLocation.find_active()
            return render_template('inventory/form.html', warehouses=warehouses, products=products, storage_locations=storage_locations, mode='add')

        # Concurrency-safe capacity reservation
        if loc and capacity_needed > 0:
            succ = loc.atomic_add_used_capacity(capacity_needed)
            if not succ:
                flash('Capacity limit exceeded during concurrent request. Please retry.', 'danger')
                warehouses = Warehouse.find_active()
                products = Product.find_active()
                storage_locations = StorageLocation.find_active()
                return render_template('inventory/form.html', warehouses=warehouses, products=products, storage_locations=storage_locations, mode='add')

        wh = Warehouse.get_by_id(warehouse_id)
        if wh and capacity_needed > 0:
            wh.update(used_capacity=wh.used_capacity + capacity_needed)

        # Create Inventory Record
        inventory = Inventory.create(
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=quantity,
            min_stock=min_stock,
            max_stock=max_stock,
            storage_location_id=storage_location_id
        )

        # Log initial Stock In transaction if initial quantity > 0
        if quantity > 0:
            InventoryTransaction.create(
                inventory_id=inventory.id,
                transaction_type='stock_in',
                quantity=quantity,
                performed_by=current_user.id if current_user and hasattr(current_user, 'id') else 'system',
                reference='INITIAL_STOCK',
                notes='Initial stock assigned during inventory registration',
                storage_location_id=storage_location_id,
                capacity_used=capacity_needed
            )

        flash('Product inventory assigned to warehouse successfully!', 'success')
        return redirect(url_for('inventory.list_inventory'))

    warehouses = Warehouse.find_active()
    products = Product.find_active()
    storage_locations = StorageLocation.find_active()
    return render_template('inventory/form.html', warehouses=warehouses, products=products, storage_locations=storage_locations, mode='add', inventory=None)


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
    if inventory.storage_location_id:
        inventory.storage_location = StorageLocation.get_by_id(inventory.storage_location_id)

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
#  STOCK IN — Add stock to inventory with capacity validation
# ---------------------------------------------------------------------------
@inventory_bp.route('/stock-in', methods=['GET', 'POST'])
@login_required
def stock_in():
    """Perform Stock In movement with concurrency-safe capacity validation."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        inventory_id = data.get('inventory_id', '').strip()
        quantity = int(data.get('quantity', 0))
        reference = data.get('reference', '').strip()
        notes = data.get('notes', '').strip()

        errors = []
        if not inventory_id:
            errors.append('Please select an inventory item.')
        if quantity <= 0:
            errors.append('Quantity must be greater than zero.')

        inventory = Inventory.get_by_id(inventory_id) if inventory_id else None
        if inventory_id and not inventory:
            errors.append('Selected inventory record not found.')

        if inventory and quantity > 0 and inventory.would_exceed_max(quantity):
            available_space = inventory.max_stock - inventory.quantity
            errors.append(
                f'Cannot add {quantity} units. Max stock limit is {inventory.max_stock}. '
                f'Current stock: {inventory.quantity}. Available space: {available_space} units.'
            )

        prod = Product.get_by_id(inventory.product_id) if inventory else None
        wh = Warehouse.get_by_id(inventory.warehouse_id) if inventory else None
        loc = StorageLocation.get_by_id(inventory.storage_location_id) if inventory and inventory.storage_location_id else None

        capacity_needed = (quantity * prod.capacity_per_unit) if prod else 0.0

        # Validate storage location capacity if tied to a location
        if loc and capacity_needed > 0:
            if not loc.validate_capacity_available(capacity_needed):
                errors.append(
                    f'Insufficient storage capacity in location {loc.code}! '
                    f'Required: {capacity_needed} {loc.capacity_unit}, Available: {loc.available_capacity} {loc.capacity_unit}.'
                )

        if errors:
            if request.is_json:
                return jsonify({'error': errors[0], 'errors': errors}), 400
            for error in errors:
                flash(error, 'danger')
            return render_template('inventory/stock_in.html', inventory_list=_build_inventory_list())

        # Atomic concurrency-safe capacity update
        if loc and capacity_needed > 0:
            succ = loc.atomic_add_used_capacity(capacity_needed)
            if not succ:
                err_msg = 'Capacity limit exceeded during simultaneous stock request. Operation cancelled to prevent overflow.'
                if request.is_json:
                    return jsonify({'error': err_msg}), 409
                flash(err_msg, 'danger')
                return render_template('inventory/stock_in.html', inventory_list=_build_inventory_list())

        if wh and capacity_needed > 0:
            wh.update(used_capacity=wh.used_capacity + capacity_needed)

        # Increase stock quantity
        inventory.adjust_quantity(quantity)

        # Log transaction
        txn = InventoryTransaction.create(
            inventory_id=inventory.id,
            transaction_type='stock_in',
            quantity=quantity,
            performed_by=current_user.id if current_user and hasattr(current_user, 'id') else 'system',
            reference=reference or None,
            notes=notes or None,
            storage_location_id=loc.id if loc else None,
            capacity_used=capacity_needed
        )

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f'Successfully added {quantity} units to {prod.name} ({wh.name})',
                'transaction': {
                    'id': txn.id,
                    'inventory_id': inventory.id,
                    'quantity': quantity,
                    'capacity_used': capacity_needed,
                    'created_at': format_datetime(txn.created_at)
                }
            })

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
    """Perform Stock Out movement and release storage capacity."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        inventory_id = data.get('inventory_id', '').strip()
        quantity = int(data.get('quantity', 0))
        reference = data.get('reference', '').strip()
        notes = data.get('notes', '').strip()

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
            if request.is_json:
                return jsonify({'error': errors[0], 'errors': errors}), 400
            for error in errors:
                flash(error, 'danger')
            return render_template('inventory/stock_out.html', inventory_list=_build_inventory_list())

        prod = Product.get_by_id(inventory.product_id)
        wh = Warehouse.get_by_id(inventory.warehouse_id)
        loc = StorageLocation.get_by_id(inventory.storage_location_id) if inventory.storage_location_id else None

        capacity_released = quantity * prod.capacity_per_unit if prod else 0.0

        # Decrease stock quantity
        inventory.adjust_quantity(-quantity)

        # Release storage capacity atomically
        if loc and capacity_released > 0:
            loc.atomic_release_used_capacity(capacity_released)

        if wh and capacity_released > 0:
            wh.update(used_capacity=max(0.0, wh.used_capacity - capacity_released))

        # Log transaction
        txn = InventoryTransaction.create(
            inventory_id=inventory.id,
            transaction_type='stock_out',
            quantity=quantity,
            performed_by=current_user.id if current_user and hasattr(current_user, 'id') else 'system',
            reference=reference or None,
            notes=notes or None,
            storage_location_id=loc.id if loc else None,
            capacity_used=capacity_released
        )

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f'Successfully removed {quantity} units from {prod.name} ({wh.name})',
                'transaction': {
                    'id': txn.id,
                    'inventory_id': inventory.id,
                    'quantity': quantity,
                    'capacity_released': capacity_released,
                    'created_at': format_datetime(txn.created_at)
                }
            })

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
    loc_map = {l.id: l for l in StorageLocation.find_active()}

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
                if inv.storage_location_id:
                    inv.storage_location = loc_map.get(inv.storage_location_id)
            inv_cache[txn.inventory_id] = inv
        txn.inventory = inv_cache.get(txn.inventory_id)
        if txn.storage_location_id:
            txn.storage_location = loc_map.get(txn.storage_location_id)
        if txn.performed_by not in user_cache:
            user_cache[txn.performed_by] = User.get_by_id(txn.performed_by)
        txn.user = user_cache.get(txn.performed_by)

    if request.args.get('format') == 'json' or request.is_json:
        return jsonify({
            'page': page,
            'per_page': per_page,
            'total': total,
            'transactions': [
                {
                    'id': t.id,
                    'inventory_id': t.inventory_id,
                    'product_name': t.inventory.product.name if t.inventory and t.inventory.product else None,
                    'product_sku': t.inventory.product.sku if t.inventory and t.inventory.product else None,
                    'warehouse_name': t.inventory.warehouse.name if t.inventory and t.inventory.warehouse else None,
                    'storage_location_code': t.storage_location.code if t.storage_location else None,
                    'transaction_type': t.transaction_type,
                    'quantity': t.quantity,
                    'capacity_used': t.capacity_used,
                    'reference': t.reference,
                    'notes': t.notes,
                    'performed_by': t.user.username if t.user else t.performed_by,
                    'created_at_ist': format_datetime(t.created_at)
                } for t in transactions
            ]
        })

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

