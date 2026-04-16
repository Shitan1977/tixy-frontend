from django.conf import settings


def api_settings(request):
    return {
        "API_BASE_URL": getattr(settings, "API_BASE_URL", "").rstrip("/"),
    }
