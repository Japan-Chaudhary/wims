"""
scratch/test_capacity_ist.py
-----------------------------
Comprehensive test suite for WIMS capacity endpoints and IST timezone validation.
"""

import sys
import unittest
from datetime import datetime
import threading
import json

from app import create_app
from database import mongo
from models.warehouse import Warehouse
from models.zone import Zone
from models.storage_location import StorageLocation
from models.product import Product
from models.inventory import Inventory
from models.transaction import InventoryTransaction
from models.reservation import CapacityReservation
from utils import to_ist, format_datetime, IST


class WIMSVerificationTest(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Login admin user
        with self.client.session_transaction() as sess:
            from models.user import User
            admin = User.get_by_username('admin')
            if admin:
                sess['_user_id'] = admin.id

    def tearDown(self):
        self.ctx.pop()

    def test_01_timezone_ist(self):
        print("\n--- Test 01: IST Timezone Handling ---")
        now = datetime.now()
        ist_now = to_ist(now)
        formatted = format_datetime(now)
        print(f"Current Raw: {now}, IST: {ist_now}, Formatted: '{formatted}'")

        self.assertIn('IST', formatted)
        self.assertIn('2026', formatted)
        print("[OK] IST timezone conversion and formatting verified!")

    def test_02_models_creation(self):
        print("\n--- Test 02: Model Creation & Capacity Units ---")

        # Warehouse with capacity unit
        wh = Warehouse.create(name="Test Central WH", location="Mumbai", capacity=1000.0, capacity_unit="KG")
        self.assertIsNotNone(wh.id)
        self.assertEqual(wh.capacity_unit, "KG")

        # Zone
        zone = Zone.create(name="Cold Zone A", code="ZONE-A", warehouse_id=wh.id, max_capacity=500.0, capacity_unit="KG")
        self.assertIsNotNone(zone.id)

        # Storage Location
        loc = StorageLocation.create(name="Shelf 101", code="LOC-101", warehouse_id=wh.id, zone_id=zone.id, max_capacity=100.0, capacity_unit="KG")
        self.assertIsNotNone(loc.id)
        self.assertEqual(loc.available_capacity, 100.0)

        # Product with capacity_per_unit
        prod = Product.create(name="Frozen Apples", sku="APP-FROZ-01", category="Food", unit_price=15.0, unit="box", capacity_per_unit=5.0, capacity_unit="KG")
        self.assertIsNotNone(prod.id)
        self.assertEqual(prod.capacity_per_unit, 5.0)

        print("[OK] Warehouse, Zone, StorageLocation, and Product created successfully!")

    def test_03_concurrency_safe_capacity(self):
        print("\n--- Test 03: Concurrency-Safe Storage Location Capacity ---")
        wh = Warehouse.create(name="Concurrency WH", capacity=500.0, capacity_unit="KG")
        loc = StorageLocation.create(name="Concurrency Loc", code="CONC-LOC", warehouse_id=wh.id, max_capacity=10.0, capacity_unit="KG")

        results = []

        def worker(amount):
            with self.app.app_context():
                loc_obj = StorageLocation.get_by_id(loc.id)
                res = loc_obj.atomic_add_used_capacity(amount)
                results.append(res)

        # Launch 5 concurrent threads each trying to add 3.0 KG capacity (Total = 15.0 KG, but max is 10.0 KG)
        threads = [threading.Thread(target=worker, args=(3.0,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is False)
        final_loc = StorageLocation.get_by_id(loc.id)

        print(f"Concurrent requests: 5 x 3.0 KG into 10.0 KG location. Successes: {successes}, Failures: {failures}")
        print(f"Final Used Capacity: {final_loc.used_capacity} / Max: {final_loc.max_capacity}")

        # Maximum 3 requests (3.0 * 3 = 9.0 KG <= 10.0 KG) should succeed!
        self.assertTrue(successes <= 3)
        self.assertTrue(final_loc.used_capacity + final_loc.reserved_capacity <= final_loc.max_capacity)
        print("[OK] Invariant (Used + Reserved <= Max) guaranteed under concurrency!")

    def test_04_storage_endpoints(self):
        print("\n--- Test 04: Storage API Endpoints ---")
        wh = Warehouse.create(name="API WH", capacity=1000.0, capacity_unit="Pieces")
        loc = StorageLocation.create(name="API Bin 1", code="BIN-01", warehouse_id=wh.id, max_capacity=50.0, capacity_unit="Pieces")

        # 1. GET /storage/{id}/capacity
        res = self.client.get(f'/storage/{loc.id}/capacity')
        self.assertEqual(res.status_code, 200)
        cap_data = res.get_json()
        self.assertEqual(cap_data['max_capacity'], 50.0)
        self.assertEqual(cap_data['available_capacity'], 50.0)

        # 2. POST /storage/{id}/reserve
        res = self.client.post(f'/storage/{loc.id}/reserve', json={
            'reserved_capacity': 20.0,
            'notes': 'Test reservation'
        })
        self.assertEqual(res.status_code, 201)
        res_data = res.get_json()
        self.assertTrue(res_data['success'])
        reservation_id = res_data['reservation']['id']

        # Verify capacity updated
        loc_check = StorageLocation.get_by_id(loc.id)
        self.assertEqual(loc_check.reserved_capacity, 20.0)
        self.assertEqual(loc_check.available_capacity, 30.0)

        # 3. POST /reservation/{id}/confirm
        res = self.client.post(f'/reservation/{reservation_id}/confirm', json={})
        self.assertEqual(res.status_code, 200)
        loc_confirmed = StorageLocation.get_by_id(loc.id)
        self.assertEqual(loc_confirmed.reserved_capacity, 0.0)
        self.assertEqual(loc_confirmed.used_capacity, 20.0)

        # 4. DELETE /reservation/{id} (Create another and cancel)
        res_res = self.client.post(f'/storage/{loc.id}/reserve', json={'reserved_capacity': 10.0})
        res2_id = res_res.get_json()['reservation']['id']
        del_res = self.client.delete(f'/reservation/{res2_id}', headers={'Accept': 'application/json'})
        self.assertEqual(del_res.status_code, 200)

        print("[OK] Storage reservation, capacity validation, confirm, and cancel endpoints verified!")

    def test_05_warehouse_utilization_and_alerts(self):
        print("\n--- Test 05: Warehouse Utilization & Capacity Alerts ---")
        wh = Warehouse.create(name="Utilization WH", capacity=100.0, capacity_unit="Pallets")
        loc = StorageLocation.create(name="Pallet Rack 1", code="RACK-1", warehouse_id=wh.id, max_capacity=100.0, capacity_unit="Pallets")
        loc.atomic_add_used_capacity(85.0)  # 85% utilized -> trigger warning alert

        # GET /warehouses/{id}/utilization
        res = self.client.get(f'/warehouses/{wh.id}/utilization?format=json')
        self.assertEqual(res.status_code, 200)
        ut_data = res.get_json()
        self.assertEqual(ut_data['capacity_metrics']['utilization_percentage'], 85.0)

        # GET /alerts/capacity
        res = self.client.get('/alerts/capacity?format=json&threshold=80')
        self.assertEqual(res.status_code, 200)
        alert_data = res.get_json()
        self.assertGreaterEqual(alert_data['total_alerts'], 1)

        print("[OK] Warehouse utilization and capacity alerts verified!")

    def test_06_smart_allocation(self):
        print("\n--- Test 06: Smart Storage Allocation ---")
        wh = Warehouse.create(name="Allocation WH", capacity=200.0, capacity_unit="Boxes")
        loc1 = StorageLocation.create(name="Loc A", code="LOC-A", warehouse_id=wh.id, max_capacity=30.0, capacity_unit="Boxes")
        loc2 = StorageLocation.create(name="Loc B", code="LOC-B", warehouse_id=wh.id, max_capacity=50.0, capacity_unit="Boxes")

        prod = Product.create(name="Bulk Cereals", sku="CER-BULK", unit_price=10.0, capacity_per_unit=2.0, capacity_unit="Boxes")

        # Request 35 units of cereal = 70 Boxes capacity needed
        # Loc B (50 Boxes) can take 25 units (50 Boxes)
        # Loc A (30 Boxes) can take 10 units (20 Boxes)
        res = self.client.post('/inventory/smart-allocation', json={
            'product_id': prod.id,
            'quantity': 35
        })
        self.assertEqual(res.status_code, 200)
        alloc_data = res.get_json()
        self.assertTrue(alloc_data['fully_allocated'])
        self.assertEqual(len(alloc_data['allocations']), 2)

        print(f"Smart Allocation Distribution: {alloc_data['allocations']}")
        print("[OK] Smart storage allocation recommended distribution across compatible locations!")

    def test_07_transactions_ist_format(self):
        print("\n--- Test 07: Transactions API with IST Timestamp ---")
        res = self.client.get('/inventory/transactions?format=json')
        self.assertEqual(res.status_code, 200)
        txn_data = res.get_json()
        self.assertIn('transactions', txn_data)
        if txn_data['transactions']:
            sample_txn = txn_data['transactions'][0]
            print(f"Sample Transaction IST timestamp: '{sample_txn['created_at_ist']}'")
            self.assertIn('IST', sample_txn['created_at_ist'])

        print("[OK] Transaction audit log with IST timestamps verified!")


if __name__ == '__main__':
    unittest.main()
