# core/services/tixy_api.py
# -----------------------------------------------------------------------------
# Wrapper centralizzato per tutte le chiamate HTTP al backend Tixy API.
# - Unifica GET/POST/PATCH/… con _api_request (Bearer opzionale).
# - Espone funzioni di alto livello usate dalle views.
# - Gestisce timeout da settings.REQUESTS_TIMEOUT (fallback 8s).
# -----------------------------------------------------------------------------

from __future__ import annotations

import requests
from django.conf import settings


# ---------------------------
# Helpers di basso livello
# ---------------------------

def _timeout() -> int:
    """Timeout di default per le richieste HTTP."""
    return getattr(settings, "REQUESTS_TIMEOUT", 8)


def _api_request(method: str, path: str, *, params: dict | None = None,
                 json: dict | None = None, token: str | None = None,
                 timeout: int | None = None):
    """Richiesta HTTP generica con gestione base del Bearer Token."""
    base = settings.API_BASE_URL.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = requests.request(
        method=method,
        url=url,
        params=params or {},
        json=json or {},
        headers=headers,
        timeout=timeout or _timeout(),
    )
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        # includo il body per debug lato FE/log
        raise requests.HTTPError(f"{e} | body={r.text}") from e
    # se non c'è JSON (204 No Content), ritorno None
    return r.json() if r.content and r.headers.get("Content-Type", "").startswith("application/json") else None


def _api_get(path: str, params: dict | None = None):
    return _api_request("GET", path, params=params)


def _api_post(path: str, json: dict | None = None):
    return _api_request("POST", path, json=json)


def _auth_headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------------------------
# SEARCH / AUTOCOMPLETE
# ---------------------------

def search_performances(q=None, date=None, city=None, page=None, ordering=None, page_size=None):
    params: dict = {}
    if q:         params["q"] = q
    if date:      params["date"] = date
    if city:      params["city"] = city
    if page:      params["page"] = page
    if ordering:  params["ordering"] = ordering
    if page_size: params["page_size"] = page_size   # <-- aggiungi questo
    return _api_get("search/performances/", params=params)


def autocomplete(kind: str = "event", q: str = "", limit: int = 10):
    return _api_get("autocomplete/", params={"type": kind, "q": q, "limit": limit})


# ---------------------------
# DETTAGLI EVENTO / PERFORMANCE
# ---------------------------

def get_performance(perf_id: int):
    return _api_get(f"performances/{perf_id}/")


def get_performance_listings(perf_id: int, page: int | str | None = None):
    params = {"page": page} if page else None
    return _api_get(f"performances/{perf_id}/listings/", params=params)


def get_event(event_id: int):
    return _api_get(f"eventi/{event_id}/")


# ---------------------------
# LISTINGS / CHECKOUT
# ---------------------------

def get_listing(listing_id: int):
    return _api_get(f"listings/{listing_id}/")


def listing_preview(listing_id: int, qty: int, fee_percent: float | None = None, fee_flat: float | None = None):
    payload: dict = {"qty": qty}
    if fee_percent is not None:
        payload["fee_percent"] = fee_percent
    if fee_flat is not None:
        payload["fee_flat"] = fee_flat
    return _api_post(f"listings/{listing_id}/preview/", json=payload)


def checkout_start(payload: dict):
    # payload conforme al serializer del backend (CheckoutStartSerializer)
    return _api_post("checkout/start/", json=payload)


def checkout_summary(order_id: int, email: str | None = None):
    params = {"email": email} if email else None
    return _api_get(f"checkout/summary/{order_id}/", params=params)


# ---------------------------
# AUTH / USER
# ---------------------------

def api_register_user(email: str, password: str, first_name: str, last_name: str,
                      accepted_terms: bool = True, accepted_privacy: bool = True):
    payload = {
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "accepted_terms": accepted_terms,
        "accepted_privacy": accepted_privacy,
    }
    return _api_request("POST", "register/", json=payload)


def api_confirm_otp(email: str, otp_code: str):
    return _api_request("POST", "auth/confirm-otp/", json={"email": email, "otp_code": otp_code})


def api_obtain_token(email: str, password: str):
    return _api_request("POST", "auth/token/", json={"email": email, "password": password})


def api_get_profile(token: str):
    return _api_request("GET", "profile/", token=token)


# ---------------------------
# EVENT FOLLOW / PRO
# ---------------------------

def api_event_follow_create(token: str, event_id: int):
    """
    Attiva le notifiche per un evento.
    In caso di vincolo unique/già attivo, ritorna {"detail": "already-following"}.
    """
    base = settings.API_BASE_URL.rstrip("/")
    url = f"{base}/event-follows/"
    payload = {"event": event_id}
    r = requests.post(
        url,
        json=payload,
        headers=_auth_headers(token),
        timeout=_timeout(),
    )
    if r.status_code in (200, 201):
        return r.json()
    # gestione "unique"/già attivo senza sollevare eccezione
    if r.status_code == 400 and "unique" in (r.text or "").lower():
        return {"detail": "already-following"}
    r.raise_for_status()


def api_event_follow_status(token: str, event_id: int) -> bool:
    base = settings.API_BASE_URL.rstrip("/")
    url = f"{base}/event-follows/"
    r = requests.get(
        url,
        params={"event": event_id},
        headers=_auth_headers(token),
        timeout=_timeout(),
    )
    if r.status_code == 401:
        return False
    r.raise_for_status()
    data = r.json()
    items = data.get("results", data if isinstance(data, list) else [])
    return bool(items)


def api_abbonamento_create(token: str, *, plan_id: int | None = None, prezzo: str = "6.99",
                           durata_giorni: int | None = None):
    """
    Crea un abbonamento (puoi passare plan_id oppure solo prezzo/durata_giorni).
    """
    payload: dict = {"prezzo": str(prezzo)}
    if plan_id:
        payload["plan"] = plan_id
    if durata_giorni is not None:
        # campo custom lato backend (oppure ignorato a seconda dell'implementazione)
        payload["data_fine_days"] = durata_giorni

    base = settings.API_BASE_URL.rstrip("/")
    url = f"{base}/abbonamenti/"
    r = requests.post(
        url,
        json=payload,
        headers=_auth_headers(token),
        timeout=_timeout(),
    )
    r.raise_for_status()
    return r.json()


def api_monitoraggio_create(token: str, *, abbonamento_id: int,
                            event_id: int | None = None, performance_id: int | None = None,
                            filters: dict | None = None):
    """
    Crea il monitoraggio collegato all'abbonamento (per evento o performance).
    """
    payload: dict = {"abbonamento": abbonamento_id}
    if event_id:
        payload["evento"] = event_id
    if performance_id:
        payload["performance"] = performance_id
    if filters:
        payload["filters_json"] = filters

    base = settings.API_BASE_URL.rstrip("/")
    url = f"{base}/monitoraggi/"
    r = requests.post(
        url,
        json=payload,
        headers=_auth_headers(token),
        timeout=_timeout(),
    )
    r.raise_for_status()
    return r.json()


# ---------------------------
# PASSWORD RESET / OTP resend
# ---------------------------

def api_password_reset_start(email: str):
    return _api_request("POST", "auth/password-reset/", json={"email": email})


def api_password_reset_confirm(uid: str, token: str, new_password: str):
    payload = {"uid": uid, "token": token, "new_password": new_password}
    return _api_request("POST", "auth/password-reset-confirm/", json=payload)


def api_resend_otp(email: str):
    return _api_request("POST", "auth/resend-otp/", json={"email": email})


# ---------------------------
# TOP LISTINGS / SELLERS
# ---------------------------

def get_top_listings(limit: int = 40, offset: int = 0, dedupe: str = "seller"):
    params = {"limit": limit, "offset": offset, "dedupe": dedupe}
    return _api_get("listings/top/", params=params)


def get_sellers_list(limit: int = 40, offset: int = 0, ordering: str | None = "-rating_avg"):
    """
    Prova /sellers/ (se presente nel backend), altrimenti fallback su /listings/top/?dedupe=seller
    e costruisce la lista aggregata dei venditori.
    Ritorna sempre {"count": int, "results": list}.
    """
    base = settings.API_BASE_URL.rstrip("/")

    # 1) Endpoint nativo (se esiste)
    try:
        params = {"limit": limit, "offset": offset}
        if ordering:
            params["ordering"] = ordering
        r = requests.get(f"{base}/sellers/", params=params, timeout=_timeout())
        r.raise_for_status()
        data = r.json() or {}
        if isinstance(data, dict) and data.get("count"):
            return data
        if isinstance(data, list) and data:
            return {"count": len(data), "results": data}
    except Exception:
        pass

    # 2) Fallback costruito da /listings/top/?dedupe=seller
    try:
        params = {"limit": limit, "offset": offset, "dedupe": "seller"}
        r = requests.get(f"{base}/listings/top/", params=params, timeout=_timeout())
        r.raise_for_status()
        raw = r.json() or {}
        rows = raw.get("results", raw if isinstance(raw, list) else []) or []
        results = []
        for it in rows:
            it = it or {}
            s = (it.get("seller_info") or {})
            results.append({
                "id": it.get("seller") or s.get("id"),
                "first_name": s.get("first_name"),
                "last_name": s.get("last_name"),
                "rating_avg": it.get("seller_rating_avg"),
                "reviews_count": it.get("seller_reviews_count") or 0,
                "listings_count": it.get("seller_listings_count") or it.get("qty") or 0,
            })
        count = raw.get("count")
        if count is None:
            count = len(results)
        return {"count": count, "results": results}
    except Exception:
        return {"count": 0, "results": []}


# ---------------------------
# RECENSIONI
# ---------------------------

def api_reviews_list(venditore: int, page: int | None = None):
    params = {"venditore": venditore}
    if page:
        params["page"] = page
    return _api_get("reviews/", params=params)


def api_reviews_stats(venditore: int):
    return _api_get("reviews/stats/", params={"venditore": venditore})


def api_review_create(token: str, *, venditore: int, order: int, rating: int, testo: str):
    payload = {"venditore": venditore, "order": order, "rating": rating, "testo": testo}
    return _api_request("POST", "reviews/", json=payload, token=token)
def api_follows_list(token: str, page: int = 1, page_size: int = 20):
    return _api_request("GET", "follows/my/", params={"page": page, "page_size": page_size}, token=token)

def api_follow_set_active(token: str, follow_id: int, active: bool):
    return _api_request("PATCH", f"event-follows/{follow_id}/", json={"active": active}, token=token)

def api_follow_delete(token: str, follow_id: int):
    return _api_request("DELETE", f"event-follows/{follow_id}/", token=token)

# === AUTH GET/POST helper comodi (opzionali ma utili) ===
def _api_get_auth(path: str, *, params: dict | None = None, token: str | None = None, timeout: int | None = None):
    return _api_request("GET", path, params=params, token=token, timeout=timeout)

def _api_post_auth(path: str, *, json: dict | None = None, token: str | None = None, timeout: int | None = None):
    return _api_request("POST", path, json=json, token=token, timeout=timeout)
# === MONITORAGGI / PRO ===

def api_monitoraggi_my(token: str, page: int = 1, page_size: int = 20):
    """
    Lista monitoraggi dell'utente (free+pro a seconda del backend).
    """
    params = {"page": page, "page_size": page_size}
    return _api_get_auth("monitoraggi/my/", params=params, token=token)

def api_monitoraggi_my_pro(token: str, page: int = 1, page_size: int = 20):
    """
    SOLO monitoraggi legati ad abbonamenti PRO (endpoint custom my-pro del backend).
    Ritorna già gli oggetti collegati (evento/performance/abbonamento) se il serializer li espone.
    """
    params = {"page": page, "page_size": page_size}
    return _api_get_auth("monitoraggi/my-pro/", params=params, token=token)

def api_abbonamenti_my(token: str, page: int = 1, page_size: int = 20):
    """
    Elenco abbonamenti dell'utente loggato (il ViewSet filtra per utente).
    Utile se vuoi mostrare anche abbonamenti PRO senza monitoraggio associato.
    """
    params = {"page": page, "page_size": page_size}
    return _api_get_auth("abbonamenti/", params=params, token=token)
# ---------------------------
# I MIEI BIGLIETTI (ACQUISTI) / ORDINI
# ---------------------------

def api_my_purchases(token: str,
                     page: int = 1,
                     page_size: int = 12,
                     *,
                     past: bool = False,
                     ordering: str = "-created_at"):
    """
    Elenco dei biglietti acquistati dall'utente loggato.
    - past=False => solo eventi FUTURI (non scaduti)
    - past=True  => storico (eventi passati)
    - ordering   => default '-created_at' (desc)
    Ritorna il JSON dell'API (tipicamente {count, results, ...}).
    """
    params = {
        "page": page,
        "page_size": page_size,
        "ordering": ordering,
    }
    if past:
        params["past"] = "1"
    return _api_get_auth("my/purchases/", params=params, token=token)


def api_orders_my(token: str,
                  page: int = 1,
                  page_size: int = 20,
                  *,
                  ordering: str = "-created_at",
                  status: str | None = None):
    """
    Elenco ordini dell'utente (se il backend espone /orders/my/).
    Utile per: ultimo ordine, riepiloghi, ecc.
    """
    params = {
        "page": page,
        "page_size": page_size,
        "ordering": ordering,
    }
    if status:
        params["status"] = status
    return _api_get_auth("orders/my/", params=params, token=token)


def api_order_download_stream(token: str, order_id: int, timeout: int | None = None):
    """
    Scarica il PDF del biglietto come stream (requests.Response).
    Comodo per i proxy FE: mantiene Authorization lato server.
    Uso:
        r = api_order_download_stream(token, order_id)
        r.raise_for_status()
        bytes_pdf = r.content
    """
    base = settings.API_BASE_URL.rstrip("/")
    url = f"{base}/orders/{order_id}/download/"
    r = requests.get(
        url,
        headers=_auth_headers(token),
        stream=True,
        timeout=timeout or _timeout(),
    )
    return r
