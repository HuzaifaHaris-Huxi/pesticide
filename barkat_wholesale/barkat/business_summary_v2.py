# barkat/views/business_summary_v2.py
"""
Views for Business Summary Report V2
Displays comprehensive financial summary with filtering
"""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from datetime import date, timedelta, datetime
from decimal import Decimal
import json

from barkat.models import Business
from barkat.services.business_summary_v2 import generate_business_summary_report


@login_required
def business_summary_report_view(request):
    """
    Display business summary report with date filtering
    """
    # Get all businesses for selection
    businesses = Business.objects.filter(is_active=True, is_deleted=False)
    
    # Get selected business (default to first one)
    business_id = request.GET.get('business_id')
    if business_id:
        business = get_object_or_404(Business, pk=business_id, is_active=True)
    else:
        business = businesses.first()
        if not business:
            return render(request, 'barkat/reports/business_summary_v2.html', {
                'error': 'No active business found. Please create a business first.'
            })
    
    # Get date range (default to current month)
    today = timezone.now().date()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    else:
        # First day of current month
        start_date = today.replace(day=1)
    
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        # Today
        end_date = today
    
    # Generate report
    report_data = generate_business_summary_report(business, start_date, end_date)
    
    # Add metadata for template
    report_data['generated_at'] = timezone.now()
    report_data['businesses'] = businesses
    report_data['selected_business_id'] = business.id
    
    context = {
        'report': report_data,
        'businesses': businesses,
        'selected_business': business,
        'start_date': start_date,
        'end_date': end_date,
    }
    
    return render(request, 'barkat/reports/business_summary_v2.html', context)

@login_required
def business_summary_json_export(request):
    """
    Export business summary as JSON
    """
    business_id = request.GET.get('business_id')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if not all([business_id, start_date_str, end_date_str]):
        return JsonResponse({'error': 'Missing required parameters'}, status=400)
    
    business = get_object_or_404(Business, pk=business_id)
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    report_data = generate_business_summary_report(business, start_date, end_date)
    
    # Convert Decimal to string for JSON serialization
    def decimal_to_str(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: decimal_to_str(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [decimal_to_str(item) for item in obj]
        elif isinstance(obj, date):
            return obj.isoformat()
        return obj
    
    report_json = decimal_to_str(report_data)
    
    return JsonResponse(report_json, safe=False)

@login_required
def business_summary_print_view(request):
    """
    Printer-friendly version of business summary
    """
    business_id = request.GET.get('business_id')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if not all([business_id, start_date_str, end_date_str]):
        return HttpResponse('Missing required parameters', status=400)
    
    business = get_object_or_404(Business, pk=business_id)
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    report_data = generate_business_summary_report(business, start_date, end_date)
    report_data['generated_at'] = timezone.now()
    
    context = {
        'report': report_data,
        'business': business,
        'start_date': start_date,
        'end_date': end_date,
    }
    
    return render(request, 'barkat/reports/business_summary_print_v2.html', context)