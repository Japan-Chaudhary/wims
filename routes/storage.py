"""
routes/storage.py
-----------------
Blueprint for Storage Locations, Zones, and Capacity Reservations management.

Endpoints supported:
    POST   /storage/{id}/reserve
    DELETE /reservation/{id}
    POST   /reservation/{id}/confirm
    GET    /storage/{id}/capacity
    GET/POST /storage
    GET/POST /zones
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from models.storage_location import StorageLocation, CAPACITY_UNITS
from models.zone import Zone
from models.warehouse import Warehouse
from models.reservation import CapacityReservation
from models.product import Product
from models.inventory import Inventory
from models.transaction import InventoryTransaction
from utils import format_datetime

storage_bp = Blueprint('storage', __name__)

@storage_bp.route('/alerts/capacity', methods=['GET'])
@login_required
def alerts_capacity():
    """GET /alerts/capacity — Retrieve capacity warning alerts."""
    from routes.inventory import capacity_alerts as ca_func
    return ca_func()


@storage_bp.route('/smart-allocation', methods=['POST'])
@storage_bp.route('/inventory/smart-allocation', methods=['POST'])
@login_required
def smart_allocation_route():
    """POST /inventory/smart-allocation — Recommend or distribute stock across compatible storage locations."""
    from routes.inventory import smart_allocation as sa_func
    return sa_func()


# ---------------------------------------------------------------------------
#  STORAGE CAPACITY ENDPOINTS
# ---------------------------------------------------------------------------

@storage_bp.route('/storage/<loc_id>/capacity', methods=['GET'])
@login_required
def get_storage_capacity(loc_id):
    """GET /storage/{id}/capacity — Retrieve storage capacity metrics."""
    loc = StorageLocation.get_by_id(loc_id)
    if not loc or not loc.is_active:
        return jsonify({'error': 'Storage location not found'}), 404

    utilization_pct = 0.0
    if loc.max_capacity > 0:
        utilization_pct = round(((loc.used_capacity + loc.reserved_capacity) / loc.max_capacity) * 100, 1)

    return jsonify({
        'id': loc.id,
        'name': loc.name,
        'code': loc.code,
        'warehouse_id': loc.warehouse_id,
        'zone_id': loc.zone_id,
        'max_capacity': loc.max_capacity,
        'used_capacity': loc.used_capacity,
        'reserved_capacity': loc.reserved_capacity,
        'available_capacity': loc.available_capacity,
        'capacity_unit': loc.capacity_unit,
        'utilization_percentage': min(100.0, utilization_pct)
    })


@storage_bp.route('/storage/<loc_id>/reserve', methods=['POST'])
@login_required
def reserve_storage_capacity(loc_id):
    """POST /storage/{id}/reserve — Atomically reserve capacity in storage location."""
    loc = StorageLocation.get_by_id(loc_id)
    if not loc or not loc.is_active:
        return jsonify({'error': 'Storage location not found'}), 404

    data = request.get_json(silent=True) or request.form
    product_id = data.get('product_id')
    quantity = int(data.get('quantity', 0))
    reserved_capacity = float(data.get('reserved_capacity', 0.0))
    notes = data.get('notes', '')

    # If product specified and reserved_capacity not explicitly set, calculate using capacity_per_unit
    if product_id and reserved_capacity <= 0:
        prod = Product.get_by_id(product_id)
        if prod:
            reserved_capacity = quantity * prod.capacity_per_unit

    if reserved_capacity <= 0:
        return jsonify({'error': 'Reserved capacity must be greater than zero'}), 400

    # Perform atomic capacity check and reservation
    success = loc.atomic_reserve_capacity(reserved_capacity)
    if not success:
        return jsonify({
            'error': f'Insufficient capacity in location {loc.code}. '
                     f'Requested {reserved_capacity} {loc.capacity_unit}, '
                     f'but available is {loc.available_capacity} {loc.capacity_unit}.'
        }), 400

    # Also update aggregate reserved capacity on Warehouse
    wh = Warehouse.get_by_id(loc.warehouse_id)
    if wh:
        wh.update(reserved_capacity=wh.reserved_capacity + reserved_capacity)

    reservation = CapacityReservation.create(
        storage_location_id=loc.id,
        warehouse_id=loc.warehouse_id,
        product_id=product_id,
        quantity=quantity,
        reserved_capacity=reserved_capacity,
        capacity_unit=loc.capacity_unit,
        performed_by=current_user.id if current_user and hasattr(current_user, 'id') else 'system',
        notes=notes
    )

    if request.is_json:
        return jsonify({
            'success': True,
            'message': 'Capacity reserved successfully',
            'reservation': {
                'id': reservation.id,
                'storage_location_id': loc.id,
                'reserved_capacity': reserved_capacity,
                'capacity_unit': loc.capacity_unit,
                'status': reservation.status,
                'created_at': format_datetime(reservation.created_at)
            }
        }), 201

    flash(f'Reserved {reserved_capacity} {loc.capacity_unit} in {loc.code} successfully!', 'success')
    return redirect(url_for('storage.list_storage'))


@storage_bp.route('/reservation/<res_id>', methods=['DELETE', 'POST'])
@login_required
def cancel_reservation(res_id):
    """DELETE /reservation/{id} — Cancel capacity reservation."""
    # Check if request is a POST method acting as DELETE or standard DELETE
    if request.method == 'POST' and request.form.get('_method') != 'DELETE' and not request.path.endswith('/cancel'):
        pass

    reservation = CapacityReservation.get_by_id(res_id)
    if not reservation:
        return jsonify({'error': 'Reservation not found'}), 404

    if reservation.status != 'active':
        return jsonify({'error': f'Reservation is already {reservation.status}'}), 400

    loc = StorageLocation.get_by_id(reservation.storage_location_id)
    if loc:
        loc.atomic_cancel_reservation(reservation.reserved_capacity)

    wh = Warehouse.get_by_id(reservation.warehouse_id)
    if wh:
        wh.update(reserved_capacity=max(0.0, wh.reserved_capacity - reservation.reserved_capacity))

    reservation.update_status('cancelled')

    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({
            'success': True,
            'message': 'Reservation cancelled and capacity released',
            'reservation_id': reservation.id
        })

    flash('Reservation cancelled and capacity released.', 'success')
    return redirect(url_for('storage.list_reservations'))


@storage_bp.route('/reservation/<res_id>/confirm', methods=['POST'])
@login_required
def confirm_reservation(res_id):
    """POST /reservation/{id}/confirm — Confirm reservation, converting reserved capacity to used stock."""
    reservation = CapacityReservation.get_by_id(res_id)
    if not reservation:
        return jsonify({'error': 'Reservation not found'}), 404

    if reservation.status != 'active':
        return jsonify({'error': f'Reservation is already {reservation.status}'}), 400

    loc = StorageLocation.get_by_id(reservation.storage_location_id)
    if not loc:
        return jsonify({'error': 'Associated storage location not found'}), 404

    # Convert reserved capacity to used capacity atomically
    success = loc.atomic_confirm_reservation(reservation.reserved_capacity)
    if not success:
        return jsonify({'error': 'Failed to confirm capacity conversion'}), 400

    wh = Warehouse.get_by_id(reservation.warehouse_id)
    if wh:
        wh.update(
            reserved_capacity=max(0.0, wh.reserved_capacity - reservation.reserved_capacity),
            used_capacity=wh.used_capacity + reservation.reserved_capacity
        )

    reservation.update_status('confirmed')

    # Update or create Inventory record if product was linked
    inv = None
    if reservation.product_id:
        inv = Inventory.get_by_warehouse_product(
            warehouse_id=reservation.warehouse_id,
            product_id=reservation.product_id,
            storage_location_id=loc.id
        )
        if not inv:
            inv = Inventory.get_by_warehouse_product(
                warehouse_id=reservation.warehouse_id,
                product_id=reservation.product_id
            )
        if inv:
            inv.adjust_quantity(reservation.quantity)
        else:
            inv = Inventory.create(
                warehouse_id=reservation.warehouse_id,
                product_id=reservation.product_id,
                quantity=reservation.quantity,
                storage_location_id=loc.id
            )

        InventoryTransaction.create(
            inventory_id=inv.id,
            transaction_type='stock_in',
            quantity=reservation.quantity,
            performed_by=current_user.id if current_user and hasattr(current_user, 'id') else 'system',
            reference=f'RESERVATION_CONFIRM_{reservation.id}',
            notes=f'Confirmed reservation {reservation.id}',
            storage_location_id=loc.id,
            capacity_used=reservation.reserved_capacity
        )

    if request.is_json:
        return jsonify({
            'success': True,
            'message': 'Reservation confirmed and converted to active stock',
            'reservation_id': reservation.id,
            'inventory_id': inv.id if inv else None
        })

    flash('Reservation confirmed successfully and inventory updated!', 'success')
    return redirect(url_for('storage.list_reservations'))


# ---------------------------------------------------------------------------
#  MANAGEMENT ROUTES (STORAGE LOCATIONS, ZONES, RESERVATIONS)
# ---------------------------------------------------------------------------

@storage_bp.route('/storage', methods=['GET', 'POST'])
@login_required
def list_storage():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip().upper()
        warehouse_id = request.form.get('warehouse_id', '').strip()
        zone_id = request.form.get('zone_id', '').strip() or None
        max_capacity = request.form.get('max_capacity', 0.0, type=float)
        capacity_unit = request.form.get('capacity_unit', 'Pieces').strip()
        description = request.form.get('description', '').strip()

        errors = []
        if not name or not code or not warehouse_id:
            errors.append('Name, code, and warehouse are required.')
        if StorageLocation.get_by_code(code):
            errors.append(f'Storage location code "{code}" already exists.')

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            StorageLocation.create(
                name=name,
                code=code,
                warehouse_id=warehouse_id,
                zone_id=zone_id,
                max_capacity=max_capacity,
                capacity_unit=capacity_unit,
                description=description or None
            )
            flash(f'Storage location "{code}" created successfully!', 'success')
            return redirect(url_for('storage.list_storage'))

    warehouse_id = request.args.get('warehouse_id', '', type=str)
    search = request.args.get('q', '', type=str)
    locations = StorageLocation.find_active(search=search or None, warehouse_id=warehouse_id or None)
    warehouses = Warehouse.find_active()
    zones = Zone.find_active()

    if request.args.get('format') == 'json' or request.is_json:
        return jsonify([
            {
                'id': loc.id,
                'name': loc.name,
                'code': loc.code,
                'warehouse_id': loc.warehouse_id,
                'zone_id': loc.zone_id,
                'max_capacity': loc.max_capacity,
                'used_capacity': loc.used_capacity,
                'reserved_capacity': loc.reserved_capacity,
                'available_capacity': loc.available_capacity,
                'capacity_unit': loc.capacity_unit
            } for loc in locations
        ])

    return render_template(
        'storage/locations.html',
        locations=locations,
        warehouses=warehouses,
        zones=zones,
        capacity_units=CAPACITY_UNITS,
        warehouse_filter=warehouse_id,
        search=search
    )


@storage_bp.route('/zones', methods=['GET', 'POST'])
@login_required
def list_zones():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip().upper()
        warehouse_id = request.form.get('warehouse_id', '').strip()
        max_capacity = request.form.get('max_capacity', 0.0, type=float)
        capacity_unit = request.form.get('capacity_unit', 'Pieces').strip()
        description = request.form.get('description', '').strip()

        errors = []
        if not name or not code or not warehouse_id:
            errors.append('Name, code, and warehouse are required.')

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            Zone.create(
                name=name,
                code=code,
                warehouse_id=warehouse_id,
                max_capacity=max_capacity,
                capacity_unit=capacity_unit,
                description=description or None
            )
            flash(f'Zone "{code}" created successfully!', 'success')
            return redirect(url_for('storage.list_zones'))

    zones = Zone.find_active()
    warehouses = Warehouse.find_active()

    if request.args.get('format') == 'json' or request.is_json:
        return jsonify([
            {
                'id': z.id,
                'name': z.name,
                'code': z.code,
                'warehouse_id': z.warehouse_id,
                'max_capacity': z.max_capacity,
                'capacity_unit': z.capacity_unit
            } for z in zones
        ])

    return render_template(
        'storage/zones.html',
        zones=zones,
        warehouses=warehouses,
        capacity_units=CAPACITY_UNITS
    )


@storage_bp.route('/reservations', methods=['GET'])
@login_required
def list_reservations():
    reservations = CapacityReservation.find_all(limit=100)
    # Enrich reservations
    wh_map = {w.id: w for w in Warehouse.find_active()}
    loc_map = {l.id: l for l in StorageLocation.find_active()}
    prod_map = {p.id: p for p in Product.find_active()}

    for r in reservations:
        r.warehouse = wh_map.get(r.warehouse_id)
        r.storage_location = loc_map.get(r.storage_location_id)
        r.product = prod_map.get(r.product_id)

    return render_template(
        'storage/reservations.html',
        reservations=reservations
    )
