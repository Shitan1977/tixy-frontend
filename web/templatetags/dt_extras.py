from django import template
from django.utils.dateparse import parse_datetime
from django.utils import timezone
register = template.Library()

@register.filter
def iso_to_datetime(value):
    if not value:
        return None
    dt = parse_datetime(value)
    if not dt:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return timezone.localtime(dt)
