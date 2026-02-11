from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from barkat.models import Party

from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q

from barkat.models import Payment


@require_GET
@login_required
def party_search(request):
    q = (request.GET.get("q") or "").strip()
    qs = Party.objects.all()

    if q:
        qs = qs.filter(display_name__icontains=q)

    qs = qs.order_by("display_name")[:10]

    data = [
        {
            "id": p.id,
            "name": p.display_name,
            "type": p.get_type_display(),
        }
        for p in qs
    ]
    return JsonResponse(data, safe=False)
