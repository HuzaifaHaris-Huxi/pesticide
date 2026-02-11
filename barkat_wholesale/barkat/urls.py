# erp/urls.py
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from .ledger_views import LedgersListView, LedgerDetailView, PartySummaryView, BusinessesView,PartyBalancesView,supplier_balance_api,customer_balance_api,party_balance_api

from .pos_print_views import PrintSalesOrderReceiptView, DebugListPrintersView,SaveAndPrintOrderView
from .quick_receipt_views import QuickReceiptPrintView,QuickReceiptCreateView,QuickReceiptUpdateView
from . import cash_out_views as from_cash_out

urlpatterns = [
    # Dashboard / Businesses
    path('login/', auth_views.LoginView.as_view(template_name='auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login', http_method_names=['get', 'post']), name='logout'),
    
    path("", BusinessesView.as_view(), name="business"),
    # Business CRUD with modals
    # List + pages
    path("businesses/", views.BusinessesListView.as_view(), name="businesses_list"),
    path("businesses/new/", views.business_add_page, name="business_new"),
    path("businesses/<int:pk>/edit/", views.business_edit_page, name="business_edit"),
    # (Optional) Keep these if used elsewhere (AJAX/integrations)
    path("businesses/<int:pk>/json/", views.business_json, name="business_json"),
    path("businesses/create/", views.business_create, name="business_create"),
    path("businesses/<int:pk>/update/", views.business_update, name="business_update"),
    path("businesses/<int:pk>/delete/", views.business_delete, name="business_delete"),
    path('api/product-detail/', views.product_detail_api, name='product_detail_api'),
    path('api/generate-barcode/', views.generate_barcode_api, name='generate_barcode_api'),
    path('api/check-barcode-exists/', views.check_barcode_exists_api, name='check_barcode_exists_api'),
    path('api/check-security-password/', views.verify_cancellation_password_api, name='check_security_password'),
    path('finance/recalculate-totals/', views.recalculate_all_totals_view, name='recalculate_all_totals'),
    path('finance/financial-summary/', views.financial_summary_view, name='financial_summary'),

    # Parties
    path("customers/", views.CustomersListView.as_view(), name="customers_list"),
    path("customers/business/<int:business_id>/", views.BusinessCustomersListView.as_view(),name="business_customers"),
    path("vendors/", views.VendorsListView.as_view(), name="vendors_list"),
    path("vendors/business/<int:business_id>/",
         views.BusinessVendorsView.as_view(),   # class name must match your view
         name="business_vendors"),
    path("party/new/", views.PartyCreateView.as_view(), name="party_create"),
    path("party/<int:pk>/", views.PartyDetailView.as_view(), name="party_detail"),
    path("party/<int:pk>/edit/", views.PartyUpdateView.as_view(), name="party_update"),
    path("parties/<int:pk>/delete/", views.party_delete, name="party_delete"),

    # Catalog
    path("catalog/categories/", views.ProductCategoriesListView.as_view(), name="product_categories"),
    path("catalog/categories/new/",views.ProductCategoryCreateView.as_view(),name="category_create"),
    path("catalog/categories/business/<int:business_id>/", views.BusinessCategoriesListView.as_view(), name="business_categories"),
    path("catalog/categories/<int:pk>/edit/", views.ProductCategoryUpdateView.as_view(), name="product_category_update"),
    path("catalog/categories/<int:pk>/delete/", views.ProductCategoryDeleteView.as_view(), name="product_category_delete"),

    # products
    path("catalog/products/", views.ProductsListView.as_view(), name="products_list"),
    path("catalog/products/export/", views.export_products_csv, name="export_products_csv"),
    path("catalog/products/new/", views.ProductCreateView.as_view(), name="product_create"),
    path("catalog/products/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),
    path("catalog/products/business/<int:business_id>/", views.BusinessProductsListView.as_view(), name="business_products"),
    path("catalog/products/business/<int:business_id>/export/", views.export_business_products_csv, name="export_business_products_csv"),
    path("catalog/products/<int:pk>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),

    # Staff
    path("staff/", views.StaffListView.as_view(), name="staff_list"),
    path("staff/add/", views.StaffCreateView.as_view(), name="staff_add"),
    path("staff/<int:pk>/edit/", views.StaffUpdateView.as_view(), name="staff_edit"),
    path("staff/business/<int:business_id>/", views.BusinessStaffListView.as_view(), name="business_staff"),
    path("staff/<int:pk>/delete/", views.StaffDeleteView.as_view(), name="staff_delete"),
    

    # Bank Accounts
    path("finance/bank-accounts/", views.BankAccountListView.as_view(), name="bankaccount_list"),
    path("bank-accounts/<int:pk>/",views.BankAccountDetailView.as_view(),name="bankaccount_detail"),
    path("finance/bank-accounts/add/", views.BankAccountCreateView.as_view(), name="bankaccount_add"),
    path("finance/bank-accounts/<int:pk>/edit/", views.BankAccountUpdateView.as_view(), name="bankaccount_edit"),
    path("finance/bank-accounts/<int:pk>/delete/", views.BankAccountDeleteView.as_view(), name="bankaccount_delete"),
    path("finance/party-balances/",PartyBalancesView.as_view(),name="party_balances"),

    #BankMovement
     # Bank movements (cash/bank)
    path("finance/movements/", views.BankMovementListView.as_view(), name="movement_list"),
    path("finance/movements/add/", views.BankMovementCreateView.as_view(), name="movement_add"),
    path("finance/movements/<int:pk>/edit/", views.BankMovementUpdateView.as_view(), name="movement_edit"),
    path("finance/movements/<int:pk>/delete/", views.BankMovementDeleteView.as_view(), name="movement_delete"),
    path("finance/party-summary/", BusinessesView.as_view(), name="party_summary"),
    path(
        "finance/party-balances/",
        PartyBalancesView.as_view(),
        name="customer_supplier_balances",
    ),
    # Purchase Orders
    path("purchases/orders/", views.PurchaseOrderListView.as_view(), name="po_list"),
    path("purchases/orders/business/<int:business_id>/", views.BusinessPurchaseOrderListView.as_view(), name="po_list_business"),
    path("purchases/orders/add/", views.PurchaseOrderCreateView.as_view(), name="po_add"),
    path("purchases/orders/<int:pk>/edit/", views.PurchaseOrderUpdateView.as_view(), name="po_edit"),
    path("purchases/orders/<int:pk>/delete/", views.PurchaseOrderDeleteView.as_view(), name="po_delete"),
    path("ajax/supplier-balance/",supplier_balance_api, name="supplier_balance_api"),
    path("ajax/party-balance/", party_balance_api, name="party_balance_base_api"),
    # Purchase Returns
    path("purchases/returns/", views.PurchaseReturnListView.as_view(), name="pr_list"),
    path("purchases/returns/business/<int:business_id>/", views.BusinessPurchaseReturnListView.as_view(), name="pr_list_business"),
    path("purchases/returns/add/", views.PurchaseReturnCreateView.as_view(), name="pr_add"),
    path("purchases/returns/<int:pk>/edit/", views.PurchaseReturnUpdateView.as_view(), name="pr_edit"),
    path("purchases/returns/<int:pk>/delete/", views.PurchaseReturnDeleteView.as_view(), name="pr_delete"),

    # Finance
    path("finance/expenses/new/",views.ExpenseCreateView.as_view(), name="finance_expense_create"),
    path("finance/expenses/", views.ExpensesListView.as_view(), name="finance_expense_list"),
    path("finance/business/<int:business_id>/expenses/", views.BusinessExpensesListView.as_view(), name="finance_business_expenses"),
    path("finance/expenses/<int:pk>/",views.ExpenseDetailView.as_view(), name="finance_expense_detail"),
    path("finance/expenses/<int:pk>/edit/",views.ExpenseUpdateView.as_view(), name="finance_expense_update"),
    path("finance/expenses/<int:pk>/delete/",views.ExpenseDeleteView.as_view(), name="finance_expense_delete"),
    path("ledgers/", LedgersListView.as_view(), name="ledgers_list"),
    path("ledgers/<str:kind>/<int:entity_id>/", LedgerDetailView.as_view(), name="ledger_detail"),

    path("finance/reports/", views.finance_reports, name="finance_reports"),
    path("finance/quick-receipts/", views.QuickReceiptListView.as_view(), name="quick_receipt_list"),
    # edit page
    path("api/party-search/", views.party_search, name="party_search"),
      # new silent print endpoint

    path(
        "finance/quick-receipt/",
        QuickReceiptCreateView.as_view(),
        name="quick_receipt_create",
    ),
    path(
        "finance/quick-receipts/<int:pk>/edit/",
        QuickReceiptUpdateView.as_view(),
        name="quick_receipt_edit",
    ),
    path(
        "finance/quick-receipts/print/",
        QuickReceiptPrintView.as_view(),
        name="quick_receipt_print",
    ),
    path("finance/receipts/<int:pk>/delete/", views.QuickReceiptDeleteView.as_view(), name="quick_receipt_delete"),

    # Cash Out URLs
    path("finance/cash-out/", 
         from_cash_out.CashOutListView.as_view(), 
         name="cash_out_list"),
    path("finance/cash-out/new/", 
         from_cash_out.CashOutCreateView.as_view(), 
         name="cash_out_create"),
    path("finance/cash-out/<int:pk>/edit/", 
         from_cash_out.CashOutUpdateView.as_view(), 
         name="cash_out_edit"),
    path("finance/cash-out/print/", 
         from_cash_out.CashOutPrintView.as_view(), 
         name="cash_out_print"),
    path("finance/cash-out/<int:pk>/delete/", 
         from_cash_out.CashOutDeleteView.as_view(), 
         name="cash_out_delete"),

    #Sales
     # lists
    # path("sales/invoices/", views.SalesInvoiceListView.as_view(), name="sales_invoice_list"),
    # path("sales/invoices/business/<int:business_id>/", views.BusinessSalesInvoiceListView.as_view(), name="business_sales_invoices"),
    path("sales/orders/add/",  views.SalesOrderCreateView.as_view(),  name="so_add"),
    path("sales/orders/<int:pk>/edit/", views.SalesOrderUpdateView.as_view(), name="so_edit"),
    path("sales/orders/<int:pk>/delete/", views.SalesOrderDeleteView.as_view(), name="so_delete"),
    path("sales/orders/<int:pk>/update-status/", views.update_sales_order_status_api, name="so_update_status"),
    path("sales/orders/", views.SalesOrderListView.as_view(), name="so_list"),
    path("sales/orders/<int:business_id>/", views.BusinessSalesOrderListView.as_view(), name="so_list_business"),
    # edit
    path("sales/invoices/<int:pk>/edit/", views.SalesInvoiceUpdateView.as_view(), name="sales_invoice_edit"),
    path("api/customer-balance/", customer_balance_api,name="customer_balance_api"),
    path("api/sales-order-search/", views.sales_order_search_api, name="sales_order_search_api"),
    path("api/sales-order-items/", views.sales_order_items_api, name="sales_order_items_api"),
    
    # User Settings
    path("settings/", views.UserSettingsUpdateView.as_view(), name="user_settings"),
    path("api/verify-cancellation-password/", views.verify_cancellation_password_api, name="verify_cancellation_password_api"),
    
    # Barcode Printing
    path("api/print-barcode-labels/", views.PrintBarcodeLabelsView.as_view(), name="print_barcode_labels"),

    path("sales/returns/", views.SalesReturnListView.as_view(), name="sr_list"),
    path("sales/returns/business/<int:business_id>/",views.SalesReturnBusinessListView.as_view(),name="sr_list_business"),
    path("sales/returns/add/", views.SalesReturnCreateView.as_view(), name="sr_add"),
    path("sales/returns/<int:pk>/edit/", views.SalesReturnUpdateView.as_view(), name="sr_edit"),
    path("sales/returns/<int:pk>/delete/", views.SalesReturnDeleteView.as_view(), name="sr_delete"),

    #--- Warehouses
    path("inventory/warehouses/", views.warehouse_list, name="warehouse_list"),
    path("inventory/warehouses/new/", views.warehouse_create, name="warehouse_create"),
    path("inventory/warehouses/<int:pk>/edit/", views.warehouse_update, name="warehouse_update"),
    
    path("inventory/warehouses/<int:pk>/", views.warehouse_detail, name="warehouse_detail"),
    path(
        "inventory/warehouses/<int:pk>/business/<int:business_id>/",
        views.business_wise_warehouse,
        name="business_wise_warehouse",
    ),

    # optional actions (wire to your existing views if already present)
    path("inventory/warehouses/<int:pk>/refill/", views.warehouse_refill, name="warehouse_refill"),
    path("inventory/stock-moves/new/", views.stock_move_create, name="stock_move_create"),
    path(
        "inventory/stock-moves/bulk/",views.stock_move_bulk, name="stock_move_bulk",
    ),
    path(
        "inventory/stock/product/<int:product_id>/",
        views.product_stock_detail,
        name="product_stock_detail",
    ),

     # Stock status
    path("inventory/stock-status/", views.stock_status, name="stock_status"),
    path("inventory/stock-status/export/", views.stock_status_excel, name="stock_status_excel"),
    path("inventory/stock-status/<int:business_id>/", views.business_stock_status, name="business_stock_status"),
    path("inventory/stock-refill/business/<int:business_id>/", views.business_refill, name="business_refill"),
    path("inventory/stock-moves/b2w/", views.stock_move_b2w, name="stock_move_b2w"),
    
    #For Print
    path("pos/print/order/<int:pk>/", PrintSalesOrderReceiptView.as_view(), name="pos_print_order"),
    path("pos/print/debug/printers/", DebugListPrintersView.as_view(), name="pos_print_debug_printers"),
    path("pos/save-and-print/", SaveAndPrintOrderView.as_view(), name="pos_save_and_print"),

]

# barkat/urls.py

# barkat/urls/business_summary_v2.py
"""
URL Configuration for Business Summary Report V2
"""
from django.urls import path
from .business_summary_v2 import (
    business_summary_report_view,
    business_summary_json_export,
    business_summary_print_view,
)

urlpatterns += [
    # Main report view
    path(
        'business-summary/',
        business_summary_report_view,
        name='report'
    ),
    
    # JSON export
    path(
        'business-summary/export/json/',
        business_summary_json_export,
        name='export_json'
    ),
    
    # Print view
    path(
        'business-summary/print/',
        business_summary_print_view,
        name='print'
    ),
]

