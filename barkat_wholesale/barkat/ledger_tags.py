# barkat/templatetags/ledger_tags.py
from decimal import Decimal
from django import template

register = template.Library()

@register.filter
def with_running_balance(rows):
    """
    Add running balance to each row in the ledger.
    Returns a list of row objects with added attributes:
    - balance: running balance (Decimal)
    - balance_abs: absolute value of balance
    - balance_side: 'Dr' or 'Cr'
    """
    if not rows:
        return []
    
    result = []
    running_balance = Decimal("0.00")
    
    for row in rows:
        # Calculate running balance
        dr = getattr(row, 'dr', Decimal("0.00")) or Decimal("0.00")
        cr = getattr(row, 'cr', Decimal("0.00")) or Decimal("0.00")
        running_balance += (dr - cr)
        
        # Add balance attributes to row
        row.balance = running_balance
        row.balance_abs = abs(running_balance)
        row.balance_side = 'Dr' if running_balance >= 0 else 'Cr'
        
        result.append(row)
    
    return result