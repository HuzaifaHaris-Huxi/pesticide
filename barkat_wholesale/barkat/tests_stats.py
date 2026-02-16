from django.test import TestCase
from decimal import Decimal
from django.contrib.auth import get_user_model
from barkat.models import (
    Business, Party, SalesOrder, SalesInvoice, PurchaseOrder,
    Payment, Expense, Product, UnitOfMeasure, ProductCategory,
    SummaryStats, BankAccount
)
from barkat.services.stats_service import recompute_summary_stats

User = get_user_model()

class SummaryStatsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.biz = Business.objects.create(name="Test Biz", code="T1", created_by=self.user, updated_by=self.user)
        self.uom = UnitOfMeasure.objects.create(name="Unit", code="U", created_by=self.user, updated_by=self.user)
        self.cat = ProductCategory.objects.create(name="Cat", business=self.biz, created_by=self.user, updated_by=self.user)
        
        # Reset SummaryStats
        SummaryStats.objects.filter(pk=1).update(
            total_receivables=0,
            total_payables=0,
            cash_in_hand=0,
            total_inventory_valuation=0
        )

    def test_recompute_all(self):
        # 1. Receivables: SO=100, INV=200, Opening=50. PayIn=30, SR=20.
        # Expected: (100+200+50) - (30+20) = 300
        customer = Party.objects.create(
            display_name="Cust", type=Party.CUSTOMER, opening_balance=50, 
            opening_balance_side='Dr', created_by=self.user, updated_by=self.user
        )
        SalesOrder.objects.create(
            business=self.biz, customer=customer, net_total=100, status='posted',
            created_by=self.user, updated_by=self.user
        )
        SalesInvoice.objects.create(
            business=self.biz, customer=customer, net_total=200, status='posted', 
            invoice_no="INV1", created_by=self.user, updated_by=self.user
        )
        from barkat.models import SalesReturn, PurchaseReturn
        SalesReturn.objects.create(
            business=self.biz, customer=customer, net_total=20, status='posted',
            created_by=self.user, updated_by=self.user
        )
        
        # 2. Payables: PO=500, Opening=100. PayOut=50, PR=50.
        # Expected: (500+100) - (50+50) = 500
        supplier = Party.objects.create(
            display_name="Supp", type=Party.VENDOR, opening_balance=100, 
            opening_balance_side='Cr', created_by=self.user, updated_by=self.user
        )
        PurchaseOrder.objects.create(
            business=self.biz, supplier=supplier, net_total=500, status='received',
            created_by=self.user, updated_by=self.user
        )
        PurchaseReturn.objects.create(
            business=self.biz, supplier=supplier, net_total=50, status='processed',
            created_by=self.user, updated_by=self.user
        )
        
        # 3. Inventory: 10 units @ 10 each = 100
        Product.objects.create(
            business=self.biz, name="P1", uom=self.uom, category=self.cat, 
            stock_qty=10, purchase_price=10, created_by=self.user, updated_by=self.user
        )
        
        # 4. Cash: Opening=1000. PayInCash=30. PayOutCash=50. ExpCash=10.
        # Expected: 1000 + 30 - 50 - 10 = 970
        BankAccount.objects.create(name="CashBox", account_type='CASH', opening_balance=1000, is_active=True)
        Payment.objects.create(business=self.biz, party=customer, direction='in', amount=30, payment_method='cash')
        Payment.objects.create(business=self.biz, party=supplier, direction='out', amount=50, payment_method='cash')
        Expense.objects.create(business=self.biz, amount=10, payment_source='cash', category='other')

        # Trigger recompute
        stats = recompute_summary_stats()
        
        self.assertEqual(stats.total_receivables, Decimal("300.00"))
        self.assertEqual(stats.total_payables, Decimal("500.00"))
        self.assertEqual(stats.total_inventory_valuation, Decimal("100.00"))
        self.assertEqual(stats.cash_in_hand, Decimal("970.00"))
