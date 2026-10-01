from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from models.warehouse import Warehouse, CAPACITY_UNITS
from models.inventory import Inventory
from models.storage_location import StorageLocation
from models.zone import Zone
from utils import Pagination

warehouses_bp = Blueprint('warehouses', __name__, url_prefix='/warehouses')


# ---------------------------------------------------------------------------
#  UTILIZATION ENDPOINT
# ---------------------------------------------------------------------------
@warehouses_bp.route('/<warehouse_id>/utilization', methods=['GET'])
@login_required
def get_warehouse_utilization(warehouse_id):
    """GET /warehouses/{id}/utilization — Retrieve detailed capacity utilization metrics."""
    wh = Warehouse.get_by_id(warehouse_id)
    if wh is None or not wh.is_active:
        return jsonify({'error': 'Warehouse not found'}), 404

    locations = StorageLocation.find_by_warehouse(wh.id)
    zones = Zone.find_by_warehouse(wh.id)

    # Compute location totals if storage locations exist
    loc_used = sum(l.used_capacity for l in locations)
    loc_reserved = sum(l.reserved_capacity for l in locations)
    loc_max = sum(l.max_capacity for l in locations)

    # Effective capacity metrics
    effective_max = loc_max if loc_max > 0 else wh.capacity
    effective_used = loc_used if loc_max > 0 else wh.used_capacity
    effective_reserved = loc_reserved if loc_max > 0 else wh.reserved_capacity
    available_capacity = max(0.0, effective_max - (effective_used + effective_reserved))

    utilization_pct = 0.0
    if effective_max > 0:
        utilization_pct = round(((effective_used + effective_reserved) / effective_max) * 100, 1)

    locations_data = [
        {
            'id': l.id,
            'code': l.code,
            'name': l.name,
            'max_capacity': l.max_capacity,
            'used_capacity': l.used_capacity,
            'reserved_capacity': l.reserved_capacity,
            'available_capacity': l.available_capacity,
            'capacity_unit': l.capacity_unit,
            'utilization_percentage': round(((l.used_capacity + l.reserved_capacity) / l.max_capacity * 100), 1) if l.max_capacity > 0 else 0.0
        } for l in locations
    ]

    zones_data = [
        {
            'id': z.id,
            'code': z.code,
            'name': z.name,
            'max_capacity': z.max_capacity,
            'capacity_unit': z.capacity_unit
        } for z in zones
    ]

    if request.args.get('format') != 'html' and (request.is_json or request.args.get('format') == 'json' or request.headers.get('Accept') == 'application/json'):
        return jsonify({
            'warehouse': {
                'id': wh.id,
                'name': wh.name,
                'location': wh.location,
                'capacity': wh.capacity,
                'capacity_unit': wh.capacity_unit
            },
            'capacity_metrics': {
                'max_capacity': effective_max,
                'used_capacity': effective_used,
                'reserved_capacity': effective_reserved,
                'available_capacity': available_capacity,
                'capacity_unit': wh.capacity_unit,
                'utilization_percentage': min(100.0, utilization_pct)
            },
            'storage_locations': locations_data,
            'zones': zones_data
        })

    return render_template(
        'warehouses/utilization.html',
        warehouse=wh,
        max_capacity=effective_max,
        used_capacity=effective_used,
        reserved_capacity=effective_reserved,
        available_capacity=available_capacity,
        utilization_pct=min(100.0, utilization_pct),
        storage_locations=locations_data,
        zones=zones_data
    )


# ---------------------------------------------------------------------------
#  LIST
# ---------------------------------------------------------------------------
@warehouses_bp.route('/')
@login_required
def list_warehouses():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('q', '', type=str).strip()

    all_warehouses = Warehouse.find_active(search=search or None)

    # Manual pagination
    total = len(all_warehouses)
    start = (page - 1) * per_page
    warehouses = all_warehouses[start:start + per_page]

    pagination = Pagination(page, per_page, total)

    # Compute stats per warehouse
    warehouse_stats = {}
    for wh in warehouses:
        inv_items = Inventory.find_active(warehouse_id=wh.id)
        total_items = sum(i.quantity for i in inv_items)
        product_count = len(inv_items)
        locs = StorageLocation.find_by_warehouse(wh.id)
        if locs:
            wh_max = sum(l.max_capacity for l in locs)
            wh_used = sum(l.used_capacity + l.reserved_capacity for l in locs)
        else:
            wh_max = wh.capacity
            wh_used = wh.used_capacity + wh.reserved_capacity

        utilization = 0.0
        if wh_max > 0:
            utilization = round((wh_used / wh_max) * 100, 1)

        warehouse_stats[wh.id] = {
            'total_items': total_items,
            'product_count': product_count,
            'utilization': min(utilization, 100.0),
            'capacity_unit': wh.capacity_unit
        }

    return render_template(
        'warehouses/list.html',
        warehouses=warehouses,
        pagination=pagination,
        search=search,
        warehouse_stats=warehouse_stats
    )


# ---------------------------------------------------------------------------
#  ADD
# ---------------------------------------------------------------------------
@warehouses_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_warehouse():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        capacity = request.form.get('capacity', 0.0, type=float)
        capacity_unit = request.form.get('capacity_unit', 'Pieces').strip()
        description = request.form.get('description', '').strip()

        errors = []
        if not name:
            errors.append('Warehouse name is required.')
        elif Warehouse.get_by_name(name):
            errors.append(f'Warehouse with name "{name}" already exists.')
        if capacity < 0:
            errors.append('Capacity cannot be negative.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('warehouses/form.html', mode='add', warehouse=None, capacity_units=CAPACITY_UNITS)

        Warehouse.create(
            name=name,
            location=location or None,
            capacity=capacity,
            capacity_unit=capacity_unit,
            description=description or None
        )
        flash(f'Warehouse "{name}" created successfully!', 'success')
        return redirect(url_for('warehouses.list_warehouses'))

    return render_template('warehouses/form.html', mode='add', warehouse=None, capacity_units=CAPACITY_UNITS)


# ---------------------------------------------------------------------------
#  VIEW
# ---------------------------------------------------------------------------
@warehouses_bp.route('/<warehouse_id>')
@login_required
def view_warehouse(warehouse_id):
    warehouse = Warehouse.get_by_id(warehouse_id)
    if warehouse is None or not warehouse.is_active:
        flash('Warehouse not found.', 'warning')
        return redirect(url_for('warehouses.list_warehouses'))

    inventory_items = Inventory.find_active(warehouse_id=warehouse.id)
    storage_locations = StorageLocation.find_by_warehouse(warehouse.id)
    zones = Zone.find_by_warehouse(warehouse.id)

    # Enrich with product objects for template
    from models.product import Product
    products_map = {p.id: p for p in Product.find_active()}
    inventory_items = [inv for inv in inventory_items if inv.product_id in products_map]
    for inv in inventory_items:
        inv.product = products_map.get(inv.product_id)

    total_quantity = sum(item.quantity for item in inventory_items)
    product_count = len(inventory_items)
    low_stock_count = sum(1 for item in inventory_items if item.is_low_stock() and item.min_stock > 0)

    if storage_locations:
        wh_max = sum(l.max_capacity for l in storage_locations)
        wh_used = sum(l.used_capacity + l.reserved_capacity for l in storage_locations)
    else:
        wh_max = warehouse.capacity
        wh_used = warehouse.used_capacity + warehouse.reserved_capacity

    utilization_pct = 0.0
    if wh_max > 0:
        utilization_pct = round((wh_used / wh_max) * 100, 1)

    return render_template(
        'warehouses/view.html',
        warehouse=warehouse,
        inventory_items=inventory_items,
        storage_locations=storage_locations,
        zones=zones,
        total_quantity=total_quantity,
        product_count=product_count,
        low_stock_count=low_stock_count,
        utilization_pct=min(100.0, utilization_pct)
    )


# ---------------------------------------------------------------------------
#  EDIT
# ---------------------------------------------------------------------------
@warehouses_bp.route('/<warehouse_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_warehouse(warehouse_id):
    warehouse = Warehouse.get_by_id(warehouse_id)
    if warehouse is None or not warehouse.is_active:
        flash('Warehouse not found.', 'warning')
        return redirect(url_for('warehouses.list_warehouses'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        capacity = request.form.get('capacity', 0.0, type=float)
        capacity_unit = request.form.get('capacity_unit', 'Pieces').strip()
        description = request.form.get('description', '').strip()

        errors = []
        if not name:
            errors.append('Warehouse name is required.')
        else:
            existing = Warehouse.get_by_name(name)
            if existing and existing.id != warehouse.id:
                errors.append(f'Warehouse name "{name}" is already used.')
        if capacity < 0:
            errors.append('Capacity cannot be negative.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('warehouses/form.html', mode='edit', warehouse=warehouse, capacity_units=CAPACITY_UNITS)

        warehouse.update(
            name=name,
            location=location or None,
            capacity=capacity,
            capacity_unit=capacity_unit,
            description=description or None
        )
        flash(f'Warehouse "{name}" updated successfully!', 'success')
        return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse.id))

    return render_template('warehouses/form.html', mode='edit', warehouse=warehouse, capacity_units=CAPACITY_UNITS)


# ---------------------------------------------------------------------------
#  DELETE (soft)
# ---------------------------------------------------------------------------
@warehouses_bp.route('/<warehouse_id>/delete', methods=['POST'])
@login_required
def delete_warehouse(warehouse_id):
    warehouse = Warehouse.get_by_id(warehouse_id)
    if warehouse is None:
        flash('Warehouse not found.', 'warning')
        return redirect(url_for('warehouses.list_warehouses'))

    warehouse.soft_delete()
    flash(f'Warehouse "{warehouse.name}" has been deleted.', 'success')
    return redirect(url_for('warehouses.list_warehouses'))

