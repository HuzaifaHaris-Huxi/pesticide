from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from .models import (
    Business, Party, BankAccount, PurchaseOrder, Expense, Payment, CashFlow,
    Product, UnitOfMeasure, ProductCategory
)
from django.contrib.auth.models import User

class InstantPaymentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="admin", password="password", email="admin@example.com")
        self.client = Client()
        self.client.login(username="admin", password="password")
        
        self.biz = Business.objects.create(name="Test Biz", code="TBZ")
        self.supplier = Party.objects.create(display_name="Test Supplier", type=Party.VENDOR)
        self.bank = BankAccount.objects.create(name="Test Bank", opening_balance=Decimal("1000.00"))
        
        self.uom = UnitOfMeasure.objects.create(name="Kg", code="KG")
        self.cat = ProductCategory.objects.create(name="General", business=self.biz)
        self.product = Product.objects.create(
            name="Test Product", 
            business=self.biz, 
            uom=self.uom, 
            category=self.cat,
            purchase_price=Decimal("10.00")
        )

    def test_po_creation_with_instant_payment_expense(self):
        """
        Verify that creating a PO with an is_paid=True expense:
        1. Creates the PO and Expense.
        2. Creates a Payment object linked to the expense.
        3. Payment has correct amount and direction.
        4. Bank account balance is reduced (via CashFlow).
        """
        url = reverse("po_add")
        
        # Prefix for items formset is 'items' as identified by debug prints
        prefix = "items"
        
        # Prepare form data
        data = {
            "business": self.biz.id,
            "supplier": self.supplier.id,
            "status": "received",
            "po_date": timezone.localdate().isoformat(),
            "tax_percent": "0.00",
            "discount_percent": "0.00",
            
            # Formset for items
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-0-product": self.product.id,
            f"{prefix}-0-quantity": "10",
            f"{prefix}-0-unit_price": "10.00",
            f"{prefix}-0-uom": self.uom.id,
            f"{prefix}-0-size_per_unit": "1.000000",
            
            # Formset for expenses
            "expenses-TOTAL_FORMS": "1",
            "expenses-INITIAL_FORMS": "0",
            "expenses-0-category": "freight",
            "expenses-0-amount": "50.00",
            "expenses-0-description": "Instant freight",
            "expenses-0-is_paid": "on",  # Checkbox 'on' means True
            "expenses-0-payment_source": "bank",
            "expenses-0-bank_account": self.bank.id,
        }
        
        response = self.client.post(url, data)
        
        # If it failed, print errors for debugging
        if response.status_code != 302:
            if "form" in response.context:
                print("Form Errors:", response.context["form"].errors)
            if "formset" in response.context:
                print("Item Formset Prefix:", response.context["formset"].prefix)
                print("Item Formset Errors:", response.context["formset"].errors)
                print("Item Formset Non-Form Errors:", response.context["formset"].non_form_errors())
            if "expense_formset" in response.context:
                print("Expense Formset Errors:", response.context["expense_formset"].errors)
                print("Expense Formset Non-Form Errors:", response.context["expense_formset"].non_form_errors())
        
        # Check for redirect (success)
        self.assertEqual(response.status_code, 302)
        
        # Verify PO and Expense
        po = PurchaseOrder.objects.latest("id")
        self.assertEqual(po.expenses.count(), 1)
        expense = po.expenses.first()
        self.assertTrue(expense.is_paid)
        self.assertIsNotNone(expense.payment)
        
        # Verify Payment
        payment = expense.payment
        self.assertEqual(payment.amount, Decimal("50.00"))
        self.assertEqual(payment.payment_source, Payment.BANK)
        self.assertEqual(payment.direction, Payment.OUT)
        self.assertEqual(payment.bank_account, self.bank)
        
        # Verify CashFlow (created for bank payment)
        cf = CashFlow.objects.filter(bank_account=self.bank).latest("id")
        self.assertEqual(cf.amount, Decimal("50.00"))
        self.assertEqual(cf.flow_type, CashFlow.OUT)
        
        # Verify double-counting fix: Expense should NOT have its own CashFlow
        self.assertIsNone(expense.cashflow)
        
        # 7. Check PO totals
        po.refresh_from_db()
        # net_total should include items (100.00) + expense (50.00) = 150.00
        # Wait, the product purchase price is 10.00, qty is 10, so 100.00.
        self.assertEqual(po.net_total, Decimal("150.00"))
        # paid_total should now include the instant payment
        self.assertEqual(po.paid_total, Decimal("50.00"), "Paid total should reflect instant payment")
        self.assertEqual(po.balance_due, Decimal("100.00"), "Balance due should be 100")

    def test_po_creation_with_unpaid_expense(self):
        """Verify that if is_paid is False, no Payment is created."""
        url = reverse("po_add")
        prefix = "items"
        
        data = {
            "business": self.biz.id,
            "supplier": self.supplier.id,
            "status": "received",
            "po_date": timezone.localdate().isoformat(),
            "tax_percent": "0.00",
            "discount_percent": "0.00",
            
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-0-product": self.product.id,
            f"{prefix}-0-quantity": "10",
            f"{prefix}-0-unit_price": "10.00",
            f"{prefix}-0-uom": self.uom.id,
            f"{prefix}-0-size_per_unit": "1.000000",
            
            "expenses-TOTAL_FORMS": "1",
            "expenses-INITIAL_FORMS": "0",
            "expenses-0-category": "freight",
            "expenses-0-amount": "100.00",
            "expenses-0-description": "Unpaid freight",
            # "expenses-0-is_paid" omitted means False
        }

        response = self.client.post(url, data)
        
        # Debug prints
        if response.status_code != 302:
            if "form" in response.context:
                print("Form Errors:", response.context["form"].errors)
            if "expense_formset" in response.context:
                print("Expense Formset Errors:", response.context["expense_formset"].errors)
        
        self.assertEqual(response.status_code, 302)

        po = PurchaseOrder.objects.latest("id")
        expense = po.expenses.first()
        
        self.assertFalse(expense.is_paid)
        self.assertIsNone(expense.payment)
        
        # Verify no Payment was created (Setup created 0, and this post should create 0)
        self.assertEqual(Payment.objects.count(), 0)
        
        # Verify PO totals
        self.assertEqual(po.net_total, Decimal("200.00")) # 100 items + 100 expense
        self.assertEqual(po.paid_total, Decimal("0.00"))
        self.assertEqual(po.balance_due, Decimal("200.00"))

    def test_finance_reports_separation(self):
        """
        Verify that finance_reports correctly separates Landed PO Expenses 
        from Operating Expenses.
        """
        # Create a PO expense (Landed)
        po = PurchaseOrder.objects.create(
            business=self.biz, 
            supplier=self.supplier, 
            created_by=self.user, 
            updated_by=self.user
        )
        Expense.objects.create(
            business=self.biz,
            purchase_order=po,
            category="freight",
            amount=Decimal("100.00"),
            date=timezone.localdate()
        )
        
        # Create an operating expense (Non-PO)
        Expense.objects.create(
            business=self.biz,
            category="rent",
            amount=Decimal("500.00"),
            date=timezone.localdate()
        )
        
        url = reverse("finance_reports")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check context
        self.assertEqual(response.context["kpi_landed_po_expenses"], Decimal("100.00"))
        self.assertEqual(response.context["kpi_operating_expenses"], Decimal("500.00"))
        self.assertEqual(response.context["kpi_expenses"], Decimal("600.00"))
