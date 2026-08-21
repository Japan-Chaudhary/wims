"""
routes/warehouses.py
--------------------
Warehouse management blueprint — full CRUD operations.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from models.warehouse import Warehouse
from models.inventory import Inventory
from utils import Pagination

warehouses_bp = Blueprint('warehouses', __name__, url_prefix='/warehouses')


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
        utilization = 0
        if wh.capacity and wh.capacity > 0:
            utilization = round((total_items / wh.capacity) * 100, 1)
        warehouse_stats[wh.id] = {
            'total_items': total_items,
            'product_count': product_count,
            'utilization': min(utilization, 100.0)
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
        capacity = request.form.get('capacity', 0, type=int)
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
            return render_template('warehouses/form.html', mode='add', warehouse=None)

        Warehouse.create(
            name=name,
            location=location or None,
            capacity=capacity,
            description=description or None
        )
        flash(f'Warehouse "{name}" created successfully!', 'success')
        return redirect(url_for('warehouses.list_warehouses'))

    return render_template('warehouses/form.html', mode='add', warehouse=None)


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

    # Enrich with product objects for template
    from models.product import Product
    products_map = {p.id: p for p in Product.find_active()}
    inventory_items = [inv for inv in inventory_items if inv.product_id in products_map]
    for inv in inventory_items:
        inv.product = products_map.get(inv.product_id)

    total_quantity = sum(item.quantity for item in inventory_items)
    product_count = len(inventory_items)
    low_stock_count = sum(1 for item in inventory_items if item.is_low_stock() and item.min_stock > 0)

    utilization_pct = 0
    if warehouse.capacity and warehouse.capacity > 0:
        utilization_pct = round((total_quantity / warehouse.capacity) * 100, 1)

    return render_template(
        'warehouses/view.html',
        warehouse=warehouse,
        inventory_items=inventory_items,
        total_quantity=total_quantity,
        product_count=product_count,
        low_stock_count=low_stock_count,
        utilization_pct=utilization_pct
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
        capacity = request.form.get('capacity', 0, type=int)
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
            return render_template('warehouses/form.html', mode='edit', warehouse=warehouse)

        warehouse.update(
            name=name,
            location=location or None,
            capacity=capacity,
            description=description or None
        )
        flash(f'Warehouse "{name}" updated successfully!', 'success')
        return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse.id))

    return render_template('warehouses/form.html', mode='edit', warehouse=warehouse)


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
