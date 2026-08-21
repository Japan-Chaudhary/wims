"""
routes/products.py
------------------
Product management blueprint — full CRUD operations.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from models.product import Product
from utils import Pagination

products_bp = Blueprint('products', __name__, url_prefix='/products')


# ---------------------------------------------------------------------------
#  LIST
# ---------------------------------------------------------------------------
@products_bp.route('/')
@login_required
def list_products():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('q', '', type=str).strip()
    category_filter = request.args.get('category', '', type=str).strip()

    all_products = Product.find_active(
        search=search or None,
        category=category_filter or None,
        sort_by='created_at',
        sort_dir=-1
    )

    categories = Product.distinct_categories()

    # Manual pagination
    total = len(all_products)
    start = (page - 1) * per_page
    products = all_products[start:start + per_page]

    pagination = Pagination(page, per_page, total)

    return render_template(
        'products/list.html',
        products=products,
        pagination=pagination,
        search=search,
        category_filter=category_filter,
        categories=categories
    )


# ---------------------------------------------------------------------------
#  ADD
# ---------------------------------------------------------------------------
@products_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        sku = request.form.get('sku', '').strip()
        category = request.form.get('category', '').strip()
        unit_price = request.form.get('unit_price', 0, type=float)
        unit = request.form.get('unit', 'pcs').strip()
        description = request.form.get('description', '').strip()

        errors = []
        if not name:
            errors.append('Product name is required.')
        if not sku:
            errors.append('SKU is required.')
        elif Product.get_by_sku(sku):
            errors.append(f'SKU "{sku}" already exists.')
        if unit_price < 0:
            errors.append('Unit price cannot be negative.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('products/form.html', mode='add', product=None)

        Product.create(
            name=name, sku=sku,
            category=category or None,
            unit_price=unit_price, unit=unit,
            description=description or None
        )
        flash(f'Product "{name}" created successfully!', 'success')
        return redirect(url_for('products.list_products'))

    return render_template('products/form.html', mode='add', product=None)


# ---------------------------------------------------------------------------
#  VIEW
# ---------------------------------------------------------------------------
@products_bp.route('/<product_id>')
@login_required
def view_product(product_id):
    product = Product.get_by_id(product_id)
    if product is None or not product.is_active:
        flash('Product not found.', 'warning')
        return redirect(url_for('products.list_products'))

    # Attach inventory list for template (product.inventory)
    from models.inventory import Inventory
    from models.warehouse import Warehouse
    all_inv = Inventory.find_active()
    product_inv = [inv for inv in all_inv if inv.product_id == product.id]
    warehouses_map = {w.id: w for w in Warehouse.find_active()}
    for inv in product_inv:
        inv.warehouse = warehouses_map.get(inv.warehouse_id)
    product.inventory = product_inv

    return render_template('products/view.html', product=product)


# ---------------------------------------------------------------------------
#  EDIT
# ---------------------------------------------------------------------------
@products_bp.route('/<product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.get_by_id(product_id)
    if product is None or not product.is_active:
        flash('Product not found.', 'warning')
        return redirect(url_for('products.list_products'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        sku = request.form.get('sku', '').strip()
        category = request.form.get('category', '').strip()
        unit_price = request.form.get('unit_price', 0, type=float)
        unit = request.form.get('unit', 'pcs').strip()
        description = request.form.get('description', '').strip()

        errors = []
        if not name:
            errors.append('Product name is required.')
        if not sku:
            errors.append('SKU is required.')
        else:
            existing = Product.get_by_sku(sku)
            if existing and existing.id != product.id:
                errors.append(f'SKU "{sku}" is already used by another product.')
        if unit_price < 0:
            errors.append('Unit price cannot be negative.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('products/form.html', mode='edit', product=product)

        product.update(
            name=name, sku=sku,
            category=category or None,
            unit_price=unit_price, unit=unit,
            description=description or None
        )
        flash(f'Product "{name}" updated successfully!', 'success')
        return redirect(url_for('products.view_product', product_id=product.id))

    return render_template('products/form.html', mode='edit', product=product)


# ---------------------------------------------------------------------------
#  DELETE (soft)
# ---------------------------------------------------------------------------
@products_bp.route('/<product_id>/delete', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.get_by_id(product_id)
    if product is None:
        flash('Product not found.', 'warning')
        return redirect(url_for('products.list_products'))

    product.soft_delete()
    flash(f'Product "{product.name}" has been deleted.', 'success')
    return redirect(url_for('products.list_products'))
