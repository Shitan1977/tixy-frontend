from __future__ import annotations

from math import ceil
from decimal import Decimal, InvalidOperation
from calendar import monthrange
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, quote

import requests
from urllib.parse import quote
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.timezone import now as dj_now
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_http_methods, require_GET

from .services import tixy_api
from .services.tixy_api import (
    search_performances, get_performance, get_performance_listings, get_event,
    get_listing, listing_preview, checkout_start, checkout_summary,
    api_event_follow_create, api_abbonamento_create, api_monitoraggio_create,
    api_get_profile, api_obtain_token, api_register_user, api_confirm_otp,
    api_event_follow_status, api_pro_alert_status, api_password_reset_start, api_password_reset_confirm,
    get_top_listings, get_alert_plans,
    _api_request,  # usato in varie helper/view
)



# =========================
# Session keys (token JWT lato API)
# =========================
SESSION_TOKEN_KEY = "api_access"
SESSION_REFRESH_KEY = "api_refresh"
SESSION_PENDING_EMAIL = "pending_email"
SESSION_PENDING_PWD = "pending_password"

# Flag di flusso PRO
SESSION_PRO_CHECKOUT = "pro_checkout"
PRO_SESSION_KEY = "pro_flow"
SIMULATED_PRO_PAYMENTS = True  # quando avremo Stripe/PayPal mettiamo False

# Prezzi/Fee
PREZZO_MESE = Decimal("6.99")
DEFAULT_FEE_PERCENT = Decimal("10.0")  # 10%
DEFAULT_FEE_FLAT = None               # nessuna fee flat

# Pagamenti “ticket” simulati
SIMULATED_PAYMENTS = True  # quando avremo Stripe/PayPal mettiamo False


# =========================
# Helper comuni
# =========================
# =========================
# Helper comuni
# =========================

def _fmt_iso_dmy_hm(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(dt_timezone.utc).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _parse_iso_z(s: str) -> datetime | None:
    """
    Parse "2025-12-19T21:30:00Z" -> datetime aware UTC
    """
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_iso_utc(s: str) -> datetime | None:
    """
    Parse ISO string -> datetime aware UTC.
    Accetta anche "Z". Se tzinfo manca, assume UTC.
    """
    dt = _parse_iso_z(s)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


def _safe_dt(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except Exception:
        return None


def D(x, default="0.00") -> Decimal:
    """Decimal safe: converte qualunque valore in Decimal, con fallback."""
    try:
        return Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def calc_change_name_fee(starts_at_iso: str):
    """
    Ritorna (fee: Decimal, msg: str, required: bool)
    REGOLA: €3,50 se mancano >= 24 ore all'evento; entro 24 ore = 0
    """
    starts = _parse_iso_utc(starts_at_iso)
    now_utc = dj_now().astimezone(dt_timezone.utc)

    if not starts:
        return Decimal("0.00"), "Cambio nominativo: data evento non disponibile.", False

    diff = starts - now_utc
    if diff >= timedelta(hours=24):
        return Decimal("3.50"), "Cambio nominativo previsto (+ € 3,50) oltre le 24 ore.", True
    return Decimal("0.00"), "Entro 24 ore dall’evento il cambio nominativo non è richiesto.", False


def _append_query_and_fragment(url, extra: dict, fragment: str | None = None):
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q.update({k: v for k, v in extra.items() if v is not None})
    return urlunparse((
        u.scheme, u.netloc, u.path, u.params,
        urlencode(q, doseq=True),
        fragment if fragment is not None else u.fragment
    ))


def _norm_title(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = s.replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s)
    return s

def get_other_dates_fallback(perf: dict, perf_id: int, api_get):
    """
    1) prova endpoint /other_dates/
    2) fallback: prende tutte le performance dello stesso luogo e stesso titolo
    """
    # 1) endpoint dedicato (se lato API lo avete, ma oggi sembra vuoto)
    try:
        data = api_get(f"/api/performances/{perf_id}/other_dates/") or []
        if isinstance(data, dict) and "results" in data:
            data = data["results"]
        if isinstance(data, list) and len(data) > 0:
            return data
    except Exception:
        pass

    # 2) fallback per luogo + titolo
    luogo_id = perf.get("luogo")
    titolo = _norm_title(perf.get("evento_nome") or "")
    if not luogo_id or not titolo:
        return []

    data = api_get(f"/api/performances/?luogo={luogo_id}&ordering=starts_at_utc&limit=200") or []
    if isinstance(data, dict) and "results" in data:
        data = data["results"]
    if not isinstance(data, list):
        return []

    out = []
    for p in data:
        if str(p.get("id")) == str(perf_id):
            continue
        if _norm_title(p.get("evento_nome") or "") != titolo:
            continue
        out.append(p)

    return out

# =========================
# Pagine semplici
# =========================
def faq(request):          return render(request, "web/faq.html")
def vantaggi(request):     return render(request, "web/vantaggi.html")
def funzioma(request):     return render(request, "web/funziona.html")
def termini(request):      return render(request, "web/termini.html")
def privacy(request):      return render(request, "web/privacy.html")
def contatti(request):     return render(request, "web/contatti.html")  # minuscolo


# =========================
# HOME con carosello “Top Venditori, Ultime eventi, Eventi del mese”
# =========================


def home(request):
    base = settings.API_BASE_URL.rstrip("/")

    # ============================================================
    # 1) TOP LISTINGS (carosello Top Biglietti / Top Venditori)
    # ============================================================
    raw = []
    try:
        data = _api_request("GET", "listings/", params={"limit": 48, "is_top": "true", "status": "ACTIVE"})
        raw = data.get("results", data if isinstance(data, list) else []) or []
    except Exception:
        raw = []

    # fallback FE: se il backend ignora is_top, filtro localmente
    def _is_top(it):
        it = it or {}
        return bool(
            it.get("is_top")
            or it.get("top")
            or (str(it.get("badge") or "").lower() == "top")
            or ("tags" in it and "top" in [str(t).lower() for t in (it.get("tags") or [])])
        )

    if raw and isinstance(raw, list):
        raw = [
            it for it in raw
            if _is_top(it)
            and str(it.get("status") or "ACTIVE").upper() == "ACTIVE"
            and int(it.get("qty") or 0) > 0
        ]

    # normalizzazione per template (TOP)
    top_listings = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        p = (it.get("performance_info") or {})
        s = (it.get("seller_info") or {})
        iso = p.get("starts_at_utc") or ""
        top_listings.append({
            **it,
            "perf_id": p.get("id"),
            "perf_name": p.get("evento_nome") or "",
            "venue": p.get("luogo_nome") or "",
            "starts_iso": iso,
            "starts_fmt": _fmt_iso_dmy_hm(iso),
            "seller_name": (
                f"{(s.get('first_name') or '').strip()} {(s.get('last_name') or '').strip()}".strip()
                or f"Venditore #{it.get('seller')}"
            ),
        })

    # ============================================================
    # 2) PERFORMANCE LIST "globale" (serve per mese + ultimi eventi)
    #    (API filtra gli eventi futuri, prendiamo "molti" e filtriamo qui)
    # ============================================================
    perf_rows = []
    try:
        data = tixy_api._api_get("performances/", params={"ordering": "starts_at_utc", "limit": 200}) or {}
        perf_rows = data.get("results", data if isinstance(data, list) else []) or []
    except Exception:
        perf_rows = []

    now = datetime.now(dt_timezone.utc)

    # normalizzazione performances
    performances = []
    for p in perf_rows:
        if not isinstance(p, dict):
            continue
        iso = p.get("starts_at_utc") or ""
        dt = _parse_iso_z(iso)

        performances.append({
            "perf_id": p.get("id"),
            "event_id": p.get("evento") or p.get("event") or p.get("evento_id"),
            "perf_name": p.get("evento_nome") or "",
            "venue": p.get("luogo_nome") or "",
            "starts_iso": iso,
            "starts_dt": dt,
            "starts_fmt": _fmt_iso_dmy_hm(iso),
            "raw": p,
        })

    # ============================================================
    # 3) EVENTI DEL MESE (mese corrente UTC) -> max 9
    # ============================================================
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = monthrange(now.year, now.month)[1]
    end_month = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)

    month_items = [
        x for x in performances
        if x["starts_dt"] and start_month <= x["starts_dt"] <= end_month
    ][:9]

    # fallback: se non ci sono eventi nel mese -> prossimi 9 FUTURI
    if not month_items:
        month_items = [
            x for x in performances
            if x["starts_dt"] and x["starts_dt"] >= now
        ][:9]

    # ============================================================
    # 4) ULTIMI EVENTI (in realtà "prossimi eventi" futuri) -> max 9
    #    NON dipendono dai biglietti top.
    # ============================================================
    latest_items = [
        x for x in performances
        if x["starts_dt"] and x["starts_dt"] >= now
    ][:9]

    return render(request, "web/home.html", {
        "top_listings": top_listings,
        "month_items": month_items,
        "latest_items": latest_items,
    })




# =========================
# Ricerca
# =========================
def search(request):
    q = (request.GET.get("q") or request.GET.get("query") or request.GET.get("term") or "").strip()
    date = (request.GET.get("date") or request.GET.get("data") or "").strip()
    city = (request.GET.get("localita") or request.GET.get("city") or request.GET.get("location") or "").strip()
    page = request.GET.get("page")
    ordering = request.GET.get("ordering")

    data, results, error = {}, [], None
    try:
        data = search_performances(q=q or None, date=date or None, city=city or None, page=page, ordering=ordering)
        results = data.get("results", data if isinstance(data, list) else [])
    except Exception as e:
        error = str(e)

    context = {
        "q": q, "date": date, "city": city,
        "results": results,
        "count": (data.get("count") if isinstance(data, dict) else len(results)) if data else 0,
        "next": data.get("next") if isinstance(data, dict) else None,
        "previous": data.get("previous") if isinstance(data, dict) else None,
        "error": error,
    }
    return render(request, "web/search.html", context)


# =========================
# Dettaglio performance + listings
# =========================


import re
from datetime import datetime, timezone as dt_timezone

def get_other_dates_by_title(perf: dict, perf_id: int):
    """
    Ritorna tutte le performance future legate allo stesso artista,
    escludendo la performance corrente.
    """
    perf_info = perf.get("performance_info") if isinstance(perf, dict) else None
    perf_info = perf_info if isinstance(perf_info, dict) else {}

    event_id = (
        perf.get("evento") or perf.get("event") or perf.get("evento_id")
        or perf_info.get("evento") or perf_info.get("event") or perf_info.get("evento_id")
    )

    titolo_raw = (
        perf.get("evento_nome")
        or perf_info.get("evento_nome")
        or perf.get("title")
        or perf_info.get("title")
        or ""
    ).strip()

    # Estraggo il nome artista dal titolo evento (es. "Artista - Tour 2026" -> "Artista")
    artista_query = re.split(r"\s[-|:–—]\s|\(|\[", titolo_raw, maxsplit=1)[0].strip()
    if not artista_query:
        artista_query = titolo_raw

    now_utc = datetime.now(dt_timezone.utc)
    rows = []

    if artista_query:
        try:
            data = _api_request(
                "GET",
                "search/performances/",
                params={"q": artista_query, "ordering": "starts_at_utc", "limit": 250},
            ) or {}
            rows.extend(data.get("results", data if isinstance(data, list) else []) or [])
        except Exception:
            pass

    if titolo_raw and _norm_title(titolo_raw) != _norm_title(artista_query):
        try:
            data = _api_request(
                "GET",
                "search/performances/",
                params={"q": titolo_raw, "ordering": "starts_at_utc", "limit": 250},
            ) or {}
            rows.extend(data.get("results", data if isinstance(data, list) else []) or [])
        except Exception:
            pass

    # Aggiungo anche le date dello stesso event_id, se disponibile.
    if event_id:
        try:
            rows.extend(_fetch_event_performances_any(int(event_id)) or [])
        except Exception:
            pass

    out = []
    seen_ids = set()
    for p in rows:
        if not isinstance(p, dict):
            continue

        pp = p.get("performance_info") or p
        if not isinstance(pp, dict):
            continue

        pid = pp.get("id") or p.get("id")
        if not pid:
            continue
        if str(pid) == str(perf_id):
            continue

        try:
            pid_int = int(pid)
        except Exception:
            continue

        if pid_int in seen_ids:
            continue

        iso = (
            pp.get("starts_at_utc") or p.get("starts_at_utc")
            or pp.get("starts_at") or p.get("starts_at") or ""
        )
        if not iso:
            continue

        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_timezone.utc)
            if dt < now_utc:
                continue
        except Exception:
            # Se la data non è parsabile non la includo: qui vogliamo solo date future certe.
            continue

        seen_ids.add(pid_int)
        out.append(
            {
                "id": pid_int,
                "starts_iso": iso,
                "starts_fmt": _fmt_iso_dmy_hm(iso),
                "city": (pp.get("citta") or p.get("citta") or pp.get("city") or p.get("city") or "").strip() or None,
                "venue": (pp.get("luogo_nome") or p.get("luogo_nome") or pp.get("venue") or p.get("venue") or "").strip() or None,
                "prezzo_min": pp.get("prezzo_min") or p.get("prezzo_min"),
            }
        )

    out.sort(key=lambda x: x.get("starts_iso") or "")
    return out





def event_listings(request, perf_id: int):
    perf, listings, external_platforms, error = None, [], [], None
    already_following = False
    already_following_pro = False
    has_external = False

    dates = []
    perf_when = ""
    event_id = None

    try:
        # 1) Dettaglio performance
        perf = get_performance(perf_id) or {}

        # 2) Data evento formattata
        starts_iso = (perf.get("starts_at_utc") or perf.get("starts_at") or "")
        perf_when = _fmt_iso_dmy_hm(starts_iso)

        # 3) ALTRE DATE (stesso titolo)
        raw_dates = get_other_dates_by_title(perf, perf_id)

        now_utc = datetime.now(dt_timezone.utc)
        norm = []

        for d in (raw_dates or []):
            pid = d.get("id")
            iso = d.get("starts_iso") or d.get("starts_at_utc") or d.get("starts_at") or ""
            if not pid or not iso:
                continue

            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=dt_timezone.utc)
                if dt < now_utc:
                    continue
            except Exception:
                continue

            norm.append({
                "id": int(pid),
                "starts_iso": iso,
                "starts_fmt": _fmt_iso_dmy_hm(iso),
                "city": (d.get("citta") or d.get("city") or "").strip() or None,
                "venue": (d.get("luogo_nome") or d.get("venue") or "").strip() or None,
                "prezzo_min": d.get("prezzo_min"),
            })

        norm.sort(key=lambda x: x["starts_iso"] or "")
        dates = norm

        # 4) event_id (serve per follow, esterne, ecc.)
        raw_event_id = (
            perf.get("evento") or perf.get("event") or perf.get("evento_id")
            or (perf.get("performance_info") or {}).get("evento")
            or (perf.get("performance_info") or {}).get("event")
            or (perf.get("performance_info") or {}).get("evento_id")
        )

        if isinstance(raw_event_id, dict):
            raw_event_id = raw_event_id.get("id") or raw_event_id.get("pk")

        try:
            event_id = int(raw_event_id) if raw_event_id not in (None, "") else None
        except Exception:
            event_id = None

        # 5) Listings Tixy per la performance
        data_listings = get_performance_listings(perf_id)
        listings = data_listings.get("results", data_listings if isinstance(data_listings, list) else [])

        # 6) (opzionale) piattaforme esterne
        if getattr(settings, "SHOW_EXTERNAL_PLATFORMS", False) and isinstance(perf, dict):
            if event_id:
                ev = get_event(event_id)
                maps = ev.get("mappings_evento", [])
                for m in maps:
                    plat = (m.get("piattaforma") or {})
                    url = m.get("url")
                    name = plat.get("nome") or "Piattaforma"
                    if url:
                        external_platforms.append({"name": name, "url": url, "note": None})
            has_external = bool(external_platforms)

        # 7) Se loggato: controlla se segue già l’evento
        try:
            token = request.session.get(SESSION_TOKEN_KEY)
            if token and event_id:
                # Estrai il titolo dell'evento per il confronto
                event_title = (perf.get("evento_nome") 
                             or (perf.get("performance_info") or {}).get("evento_nome") 
                             or "")
                already_following = api_event_follow_status(token, int(event_id))
                already_following_pro = api_pro_alert_status(token, int(event_id), event_title)
        except Exception as exc:
            already_following = False
            already_following_pro = False

    except Exception as e:
        error = str(e)

    has_tixy = bool(listings)
    show_alert_cta = not has_tixy

    alert_param = (request.GET.get("alert") or "").lower()
    pro_param = (request.GET.get("pro") or "").lower()
    following = bool(already_following or alert_param == "ok")
    
    # Se ha QUALSIASI abbonamento (gratuito O PRO), non può attivarne altri
    has_any_subscription = bool(already_following or already_following_pro)

    context = {
        "perf": perf or {},
        "perf_when": perf_when,
        "dates": dates,
        "selected_date_id": int(perf_id),

        "listings": listings or [],
        "external_platforms": external_platforms if getattr(settings, "SHOW_EXTERNAL_PLATFORMS", False) else [],
        "has_tixy": has_tixy,
        "has_external": has_external,
        "show_alert_cta": show_alert_cta,
        "already_following": already_following,
        "already_following_pro": already_following_pro,
        "has_any_subscription": has_any_subscription,
        "following": following,
        "pro_ok": pro_param == "ok",
        "error": error,
        "evento": {"id": event_id} if event_id else {},
    }
    return render(request, "web/event_listings.html", context)


# =========================
# Auth helpers
# =========================
def _require_api_login(request, *, next_url):
    token = request.session.get(SESSION_TOKEN_KEY)
    if not token:
        return redirect(reverse("login") + "?" + urlencode({"next": next_url}))

    # Verifica il token chiamando le API
    try:
        api_get_profile(token)
    except Exception:
        request.session.pop(SESSION_TOKEN_KEY, None)
        request.session.pop(SESSION_REFRESH_KEY, None)
        messages.info(request, "La sessione è scaduta. Accedi di nuovo per continuare.")
        return redirect(reverse("login") + "?" + urlencode({"next": next_url}))
    return None


# =========================
# Registrazione + OTP + Login
# =========================
def registrazione(request):
    next_url = request.GET.get("next") or reverse("home")
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        terms = bool(request.POST.get("accepted_terms"))
        privacy = bool(request.POST.get("accepted_privacy"))

        if not (email and password and first_name and last_name and terms and privacy):
            messages.error(request, "Compila tutti i campi obbligatori e accetta Termini/Privacy.")
            return render(request, "web/registrazione.html", {"next": next_url})

        try:
            api_register_user(email, password, first_name, last_name, terms, privacy)
            request.session[SESSION_PENDING_EMAIL] = email
            request.session[SESSION_PENDING_PWD] = password
            return redirect(reverse("verifica-otp") + "?" + urlencode({"email": email, "next": next_url}))
        except Exception as e:
            messages.error(request, f"Registrazione fallita: {e}")
    return render(request, "web/registrazione.html", {"next": next_url})


def verifica_otp(request):
    """
    Pagina OTP unica (gestisce anche 'resend').
    """
    email = request.GET.get("email") or request.session.get(SESSION_PENDING_EMAIL) or ""
    next_url = request.GET.get("next") or reverse("home")

    if request.method == "POST":
        action = request.POST.get("action") or "confirm"
        email = (request.POST.get("email") or email).strip().lower()

        if action == "resend":
            if not email:
                messages.error(request, "Inserisci la tua email per ricevere un nuovo codice.")
            else:
                try:
                    from .services.tixy_api import api_resend_otp
                    api_resend_otp(email)
                    if SESSION_PENDING_EMAIL not in request.session:
                        request.session[SESSION_PENDING_EMAIL] = email
                    messages.success(request, "Ti abbiamo inviato un nuovo codice OTP.")
                except Exception:
                    messages.info(request, "Se l'email è corretta, riceverai a breve un nuovo codice.")
            return render(request, "web/verifica_otp.html", {"email": email, "next": next_url})

        # conferma OTP
        otp = (request.POST.get("otp_code") or "").strip()
        if not (email and otp):
            messages.error(request, "Inserisci email e codice OTP.")
            return render(request, "web/verifica_otp.html", {"email": email, "next": next_url})

        try:
            api_confirm_otp(email, otp)
            pwd = request.session.get(SESSION_PENDING_PWD)
            tokens = api_obtain_token(email, pwd)
            request.session[SESSION_TOKEN_KEY] = tokens.get("access")
            request.session[SESSION_REFRESH_KEY] = tokens.get("refresh")
            request.session.pop(SESSION_PENDING_EMAIL, None)
            request.session.pop(SESSION_PENDING_PWD, None)
            messages.success(request, "Account verificato! Sei connesso.")
            return redirect(next_url)
        except Exception:
            messages.error(request, "Codice OTP non valido o scaduto.")

    return render(request, "web/verifica_otp.html", {"email": email, "next": next_url})


def login(request):
    next_url = request.GET.get("next") or reverse("account_admin")
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "").strip()
        remember = bool(request.POST.get("remember"))

        try:
            tokens = api_obtain_token(email, password)
            request.session[SESSION_TOKEN_KEY] = tokens.get("access")
            request.session[SESSION_REFRESH_KEY] = tokens.get("refresh")
            request.session.set_expiry(60 * 60 * 24 * 14 if remember else 0)
            messages.success(request, "Accesso eseguito.")
            return redirect(next_url)
        except Exception:
            messages.error(request, "Credenziali non valide o account non verificato.")

    return render(request, "web/login.html", {"next": next_url})


def logout_view(request):
    request.session.flush()
    messages.info(request, "Sei uscito dall'account.")
    return redirect("home")


# =========================
# Checkout (protetto) + Pagamento + Conferma
# =========================
def checkout_view(request, listing_id: int):
    """Pagina Acquista con login/registrazione inline (OTP) e poi creazione ordine."""
    next_url = request.build_absolute_uri()
    token = request.session.get(SESSION_TOKEN_KEY)

    # 1) Dati listing
    try:
        listing = get_listing(listing_id)
    except Exception as e:
        messages.error(request, f"Listing non disponibile: {e}")
        return redirect("home")

    # qty
    try:
        qty = max(1, int(request.POST.get("qty") or request.GET.get("qty") or "1"))
    except ValueError:
        qty = 1

    # 2) Preview prezzi (passa float, non Decimal)
    try:
        fee_p = float(DEFAULT_FEE_PERCENT) if DEFAULT_FEE_PERCENT is not None else None
        fee_f = float(DEFAULT_FEE_FLAT) if DEFAULT_FEE_FLAT is not None else None
        preview = listing_preview(listing_id, qty, fee_p, fee_f)
    except Exception as e:
        preview = {"error": str(e)}

    # Fallback numeri base
    unit_price = D(preview.get("unit_price")) or D((listing.get("price_each")))
    subtotal   = D(preview.get("subtotal")) or (unit_price * qty).quantize(Decimal("0.01"))
    commission = D(preview.get("commission")) or (subtotal * Decimal("0.10")).quantize(Decimal("0.01"))
    total      = D(preview.get("total")) or (subtotal + commission).quantize(Decimal("0.01"))

    # Recupero ISO UTC della performance dal listing
    perf_info = (listing.get("performance_info") or {})
    starts_iso = perf_info.get("starts_at_utc") or perf_info.get("starts_at") or ""

    # Cambio nominativo
    change_fee, change_msg, change_required = calc_change_name_fee(starts_iso)
    final_total = (total + change_fee).quantize(Decimal("0.01"))

    # 3) Profilo (se loggato)
    profilo = {}
    if token:
        try:
            profilo = api_get_profile(token) or {}
        except Exception:
            profilo = {}

    if request.method == "POST":
        action = request.POST.get("action")

        # --- LOGIN inline ---
        if action == "login":
            email = (request.POST.get("email") or "").strip().lower()
            pwd = (request.POST.get("password") or "").strip()
            try:
                tokens = api_obtain_token(email, pwd)
                request.session[SESSION_TOKEN_KEY] = tokens.get("access")
                request.session[SESSION_REFRESH_KEY] = tokens.get("refresh")
                messages.success(request, "Accesso eseguito.")
                return redirect(next_url)
            except Exception as e:
                messages.error(request, f"Login fallito: {e}")

        # --- REGISTRAZIONE inline (OTP) ---
        elif action == "register":
            email = (request.POST.get("email") or "").strip().lower()
            password = (request.POST.get("password") or "").strip()
            first_name = (request.POST.get("first_name") or "").strip()
            last_name = (request.POST.get("last_name") or "").strip()
            terms = bool(request.POST.get("accepted_terms"))
            privacy = bool(request.POST.get("accepted_privacy"))

            if not (email and password and first_name and last_name and terms and privacy):
                messages.error(request, "Compila tutti i campi e accetta Termini/Privacy.")
            else:
                try:
                    api_register_user(email, password, first_name, last_name, terms, privacy)
                    request.session[SESSION_PENDING_EMAIL] = email
                    request.session[SESSION_PENDING_PWD] = password
                    return redirect(reverse("verifica-otp") + "?" + urlencode({"email": email, "next": next_url}))
                except Exception as e:
                    messages.error(request, f"Registrazione fallita: {e}")

        # --- PROSEGUI (crea ordine) ---
        elif action == "prosegui":
            if not token:
                messages.error(request, "Per proseguire devi prima accedere o registrarti.")
            elif not request.POST.get("accepted_terms") or not request.POST.get("accepted_privacy"):
                messages.error(request, "Devi accettare Termini e Privacy.")
            else:
                payload = {
                    "listing": listing_id,
                    "qty": qty,
                    "email": profilo.get("email"),
                    "first_name": profilo.get("first_name"),
                    "last_name": profilo.get("last_name"),
                    "phone_number": profilo.get("phone_number") or "",
                    "create_account": False,
                    "accepted_terms": True,
                    "accepted_privacy": True,
                }
                if DEFAULT_FEE_PERCENT is not None:
                    payload["fee_percent"] = str(DEFAULT_FEE_PERCENT)
                if DEFAULT_FEE_FLAT is not None:
                    payload["fee_flat"] = str(DEFAULT_FEE_FLAT)

                try:
                    res = checkout_start(payload)
                    order_id = res.get("id")
                    if order_id:
                        request.session["checkout_email"] = profilo.get("email")
                        return redirect("pagamento", order_id=order_id)
                    messages.error(request, "Impossibile creare l’ordine.")
                except Exception as e:
                    messages.error(request, f"Errore creazione ordine: {e}")

    ctx = {
        "listing": listing,
        "qty": qty,
        "preview": preview,          # risposta pura dell'API
        "preview_subtotal": subtotal,
        "preview_commission": commission,
        "preview_total": total,
        "change_fee": change_fee,
        "change_msg": change_msg,
        "change_required": change_required,
        "final_total": final_total,
        "profilo": profilo,
        "auth_required": not bool(token),
    }
    return render(request, "web/checkout.html", ctx)


def payment_view(request, order_id: int):
    """Step pagamento: mostra tutti i numeri (subtotal, commission, change_fee, final_total)."""
    email = request.session.get("checkout_email") or request.GET.get("email")
    try:
        order = checkout_summary(order_id, email=email)
    except Exception as e:
        messages.error(request, f"Non riesco a caricare l’ordine: {e}")
        return redirect("home")

    qty        = int(order.get("qty") or 1)
    unit_price = D(order.get("unit_price") or (order.get("listing_info") or {}).get("price_each"))
    subtotal   = D(order.get("subtotal"));   subtotal   = (unit_price * qty).quantize(Decimal("0.01")) if subtotal <= 0 else subtotal
    commission = D(order.get("commission")); commission = (subtotal * Decimal("0.10")).quantize(Decimal("0.01")) if commission <= 0 else commission
    base_total = D(order.get("total") or order.get("total_price")); base_total = (subtotal + commission).quantize(Decimal("0.01")) if base_total <= 0 else base_total

    perf = (order.get("listing_info") or {}).get("performance_info") or {}
    starts_iso = perf.get("starts_at_utc") or perf.get("starts_at") or ""
    perf_when = _fmt_iso_dmy_hm(starts_iso)
    change_fee, change_msg, change_required = calc_change_name_fee(starts_iso)
    final_total = (base_total + change_fee).quantize(Decimal("0.01"))

    order["qty"]             = qty
    order["unit_price"]      = str(unit_price)
    order["subtotal"]        = str(subtotal)
    order["commission"]      = str(commission)
    order["total"]           = str(base_total)
    order["change_fee"]      = str(change_fee)
    order["change_required"] = bool(change_required)
    order["change_msg"]      = change_msg
    order["final_total"]     = str(final_total)

    if request.method == "POST":
        if SIMULATED_PAYMENTS:
            messages.success(request, "Pagamento simulato completato ✅")
            return redirect("ordine_confermato", order_id=order_id)
        else:
            messages.error(request, "Pagamento reale non configurato (imposta SIMULATED_PAYMENTS=True per test).")

    return render(request, "web/payment.html", {"order": order, "simulated": SIMULATED_PAYMENTS})


def order_confirmed_view(request, order_id: int):
    """Pagina finale (conferma ordine) con stessi numeri del pagamento."""
    email = request.session.get("checkout_email") or request.GET.get("email")
    try:
        order = checkout_summary(order_id, email=email)
    except Exception as e:
        messages.error(request, f"Non riesco a caricare l’ordine: {e}")
        return redirect("home")

    qty        = int(order.get("qty") or 1)
    unit_price = D(order.get("unit_price") or (order.get("listing_info") or {}).get("price_each"))
    subtotal   = D(order.get("subtotal"));   subtotal   = (unit_price * qty).quantize(Decimal("0.01")) if subtotal <= 0 else subtotal
    commission = D(order.get("commission")); commission = (subtotal * Decimal("0.10")).quantize(Decimal("0.01")) if commission <= 0 else commission
    base_total = D(order.get("total") or order.get("total_price")); base_total = (subtotal + commission).quantize(Decimal("0.01")) if base_total <= 0 else base_total

    perf = (order.get("listing_info") or {}).get("performance_info") or {}
    starts_iso = perf.get("starts_at_utc") or perf.get("starts_at") or ""
    perf_when = _fmt_iso_dmy_hm(starts_iso)
    change_fee, change_msg, change_required = calc_change_name_fee(starts_iso)
    final_total = (base_total + change_fee).quantize(Decimal("0.01"))

    order["qty"]             = qty
    order["unit_price"]      = str(unit_price)
    order["subtotal"]        = str(subtotal)
    order["commission"]      = str(commission)
    order["total"]           = str(base_total)
    order["change_fee"]      = str(change_fee)
    order["change_required"] = bool(change_required)
    order["change_msg"]      = change_msg
    order["final_total"]     = str(final_total)

    return render(request, "web/order_confirmed.html", {"order": order})


# =========================
# PRO (monitoraggi)
# =========================
def attiva_pro(request):
    """
    GET: mostra selezione piani AlertPlan (attiva_pro.html)
    POST: valida la scelta e manda al carrello (pro_cart) salvando in sessione
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    try:
        event_id = int(request.GET.get("event") or 0)
    except (TypeError, ValueError):
        event_id = 0
    
    try:
        performance_id = int(request.GET.get("performance") or 0)
    except (TypeError, ValueError):
        performance_id = 0

    if request.method == "POST":
        plan_id = request.POST.get("plan_id")
        
        if not plan_id:
            messages.error(request, "Seleziona un piano.")
            return redirect(reverse("attiva_pro") + f"?event={event_id}" if event_id else "")
        
        try:
            # Recupera il piano per ottenere i dettagli
            alert_plans_data = get_alert_plans()
            plans = alert_plans_data.get("results", alert_plans_data) if isinstance(alert_plans_data, dict) else alert_plans_data
            
            selected_plan = None
            for plan in plans:
                if str(plan.get("id")) == str(plan_id):
                    selected_plan = plan
                    break
            
            if not selected_plan:
                messages.error(request, "Piano non valido.")
                return redirect(reverse("attiva_pro") + f"?event={event_id}" if event_id else "")
            
            giorni = selected_plan.get("duration_days", 30)
            prezzo = str(selected_plan.get("price", "6.99"))
            
            request.session[PRO_SESSION_KEY] = {
                "event_id": event_id,
                "performance_id": performance_id,
                "plan_id": plan_id,
                "plan_name": selected_plan.get("name", ""),
                "giorni": giorni,
                "prezzo": prezzo,
                "next": request.GET.get("next") or request.META.get("HTTP_REFERER") or reverse("home"),
            }
            request.session.modified = True
            return redirect(reverse("pro_cart"))
            
        except Exception as e:
            messages.error(request, f"Errore durante il caricamento del piano: {e}")
            return redirect(reverse("attiva_pro") + f"?event={event_id}" if event_id else "")

    # GET - recupera i piani alert dall'API
    try:
        alert_plans_data = get_alert_plans()
        
        if alert_plans_data is None:
            messages.warning(request, "La risposta dell'API è vuota. Verifica che il backend sia attivo.")
            alert_plans = []
        elif isinstance(alert_plans_data, dict):
            # Può essere paginated con "results" o non paginated
            alert_plans = alert_plans_data.get("results", [])
            if not alert_plans and alert_plans_data:
                # Se non c'è "results" ma ci sono dati, probabilmente è un singolo oggetto o lista diretta
                alert_plans = [alert_plans_data] if alert_plans_data else []
        elif isinstance(alert_plans_data, list):
            alert_plans = alert_plans_data
        else:
            alert_plans = []
    except Exception as e:
        messages.error(request, f"Impossibile caricare i piani disponibili: {e}")
        alert_plans = []

    ctx = {
        "event_id": event_id,
        "performance_id": performance_id,
        "alert_plans": alert_plans,
        "next": request.GET.get("next") or reverse("home"),
    }
    return render(request, "web/attiva_pro.html", ctx)


@require_POST
def attiva_alert(request, event_id: int):
    back = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("home")
    guard = _require_api_login(request, next_url=_append_query_and_fragment(back, {}, fragment="alerts"))
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    try:
        res = api_event_follow_create(token, event_id)
        if isinstance(res, dict) and res.get("detail") == "already-following":
            messages.info(request, "Le notifiche erano già attive per questo evento.")
        else:
            messages.success(request, "Notifiche gratuite attivate per questo evento.")
        back = _append_query_and_fragment(back, {"alert": "ok"}, fragment="alerts")
    except Exception as e:
        messages.error(request, f"Impossibile attivare le notifiche: {e}")
        back = _append_query_and_fragment(back, {"alert": "err"}, fragment="alerts")
    return redirect(back)


def _calc_pro_plan(periodo: str, *, prezzo_mese: Decimal = PREZZO_MESE):
    """
    periodo: '1m'..'12m' oppure 'evento'
    ritorna: mesi, giorni, prezzo_tot
    """
    periodo = (periodo or "1m").strip().lower()
    if periodo.endswith("m"):
        try:
            mesi = int(periodo[:-1])
            mesi = max(1, min(12, mesi))
        except Exception:
            mesi = 1
        giorni = 30 * mesi
        prezzo = (prezzo_mese * mesi).quantize(Decimal("0.01"))
        return mesi, giorni, prezzo
    # 'evento' -> flat 6.99, durata default 60 gg
    return 0, 60, prezzo_mese.quantize(Decimal("0.01"))


def pro_cart(request):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    data = request.session.get(PRO_SESSION_KEY)
    if not data:
        messages.error(request, "Carrello PRO vuoto o scaduto.")
        return redirect("attiva_pro")

    event_id = data.get("event_id")
    performance_id = data.get("performance_id")
    plan_id = data.get("plan_id")
    periodo = (data.get("periodo") or "1m").strip().lower()
    giorni = int(data.get("giorni") or 30)
    prezzo = data.get("prezzo")
    next_url = data.get("next") or reverse("home")

    mesi = 0
    if periodo.endswith("m"):
        try:
            mesi = int(periodo[:-1])
        except Exception:
            mesi = 1

    if request.method == "POST":
        request.session[SESSION_PRO_CHECKOUT] = {
            "event_id": event_id,
            "performance_id": performance_id,
            "plan_id": plan_id,
            "periodo": periodo,
            "mesi": mesi,
            "giorni": giorni,
            "prezzo": prezzo,
            "next": next_url,
        }
        request.session.modified = True
        return redirect("pro_pagamento")

    ctx = {
        "event_id": event_id,
        "performance_id": performance_id,
        "plan_id": plan_id,
        "periodo": periodo,
        "mesi": mesi,
        "giorni": giorni,
        "prezzo": prezzo,
        "prezzo_mese": PREZZO_MESE,
        "next": next_url,
    }
    return render(request, "web/pro_cart.html", ctx)


def pro_pagamento(request):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    data = request.session.get(SESSION_PRO_CHECKOUT)
    if not data:
        messages.error(request, "Carrello PRO vuoto o scaduto.")
        return redirect("home")

    event_id = data.get("event_id")
    performance_id = data.get("performance_id")
    plan_id = data.get("plan_id")
    periodo = data.get("periodo")
    mesi = data.get("mesi")
    giorni = int(data.get("giorni") or 30)
    prezzo = data.get("prezzo")
    next_url = data.get("next") or reverse("home")

    if request.method == "POST":
        token = request.session.get(SESSION_TOKEN_KEY)
        try:
            if not SIMULATED_PRO_PAYMENTS:
                messages.error(request, "Pagamento reale non configurato.")
                return redirect(request.path)

            abb = api_abbonamento_create(
                token,
                plan_id=int(plan_id) if str(plan_id or "").isdigit() else None,
                prezzo=str(prezzo),
                durata_giorni=giorni,
                periodo=periodo,
            )
            api_monitoraggio_create(token, abbonamento_id=abb["id"], event_id=event_id, performance_id=performance_id)

            request.session.pop(SESSION_PRO_CHECKOUT, None)
            messages.success(request, "✅ Abbonamento PRO attivato! Monitoraggio creato.")
            sep = "&" if "?" in next_url else "?"
            return redirect(f"{next_url}{sep}pro=ok#alerts")
        except Exception as e:
            messages.error(request, f"Errore attivazione PRO: {e}")

    ctx = {
        "event_id": event_id,
        "plan_id": plan_id,
        "periodo": periodo,
        "mesi": mesi,
        "giorni": giorni,
        "prezzo": prezzo,
        "prezzo_mese": PREZZO_MESE,
        "next": next_url,
        "simulated": SIMULATED_PRO_PAYMENTS,
    }
    return render(request, "web/pro_payment.html", ctx)


def pro_done(request):
    next_url = request.GET.get("next")
    if next_url:
        messages.success(request, "✅ Abbonamento PRO attivato!")
        return redirect(next_url)
    return render(request, "web/pro_done.html", {})


# =========================
# Password reset
# =========================
def password_forgot_view(request):
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        if not email:
            messages.error(request, "Inserisci la tua email.")
        else:
            try:
                api_password_reset_start(email)
                messages.success(request, "Se l'email esiste, ti abbiamo inviato le istruzioni per reimpostare la password.")
                return redirect("login")
            except Exception:
                messages.success(request, "Se l'email esiste, ti abbiamo inviato le istruzioni per reimpostare la password.")
                return redirect("login")
    return render(request, "web/password_forgot.html", {})


def password_reset_confirm_view(request):
    uid = request.GET.get("uid") or request.POST.get("uid") or ""
    token = request.GET.get("token") or request.POST.get("token") or ""

    if not (uid and token):
        messages.error(request, "Link di reset non valido o incompleto.")
        return redirect("password_forgot")

    if request.method == "POST":
        new1 = request.POST.get("password1") or ""
        new2 = request.POST.get("password2") or ""
        if not new1 or not new2:
            messages.error(request, "Inserisci e conferma la nuova password.")
        elif new1 != new2:
            messages.error(request, "Le password non coincidono.")
        elif len(new1) < 8:
            messages.error(request, "La password deve avere almeno 8 caratteri.")
        else:
            try:
                api_password_reset_confirm(uid, token, new1)
                messages.success(request, "Password aggiornata. Ora puoi accedere.")
                return redirect("login")
            except Exception:
                messages.error(request, "Impossibile completare le operazioni. Il link potrebbe essere scaduto.")
    return render(request, "web/password_reset_confirm.html", {"uid": uid, "token": token})


# =========================
# Helper per account_admin
# =========================

def _api_collect_results(token: str, endpoint: str, page_size: int = 200):
    """Recupera tutti i risultati paginati da un endpoint DRF."""
    out = []
    page = 1
    while True:
        try:
            data = _api_request(
                "GET",
                endpoint,
                params={"page": page, "page_size": page_size},
                token=token,
                timeout=10,
            ) or {}
        except Exception:
            break

        rows = data.get("results", data if isinstance(data, list) else []) or []
        if not rows:
            break
        out.extend(rows)

        # Se non e una risposta paginata DRF, una pagina sola.
        if not isinstance(data, dict) or "next" not in data:
            break
        if not data.get("next"):
            break
        page += 1

    return out

def _get_active_alerts(token: str):
    """
    Recupera gli alert attivi (EventFollow + Monitoraggi PRO) dell'utente.
    Ritorna lista di dict con: id, title, type, expires_at, status
    """
    alerts = []
    
    # Alert gratuiti (EventFollow)
    try:
        rows = _api_collect_results(token, "event-follows/")
        for ef in rows:
            ev = (ef.get("evento_info") or {})
            alerts.append({
                "id": ef.get("id"),
                "title": ev.get("nome_evento") or ev.get("nome") or "Evento",
                "type": "free",
                "created_at": _fmt_iso_dmy_hm(ef.get("created_at") or ""),
                "expires_at": None,
                "status": "Attivo",
            })
    except Exception:
        pass
    
    # Monitoraggi PRO

    try:
        rows = _api_collect_results(token, "monitoraggi/my-pro/")

        for m in rows:
            mapped_status = _map_sub_status(m)
            if mapped_status != "Attivo":
                continue
            alerts.append({
                "id": m.get("id"),
                "title": m.get("event_title") or "Evento",
                "type": "pro",
                # activated_at = data attivazione del PRO
                "created_at": _fmt_iso_dmy_hm(m.get("activated_at") or ""),
                "expires_at": _fmt_iso_dmy_hm(m.get("expires_at") or ""),
                "status": mapped_status,
            })
    except Exception:
        pass

    return alerts


def _get_free_alerts_count(token: str) -> int:
    """Conta gli alert gratuiti attivi."""
    try:
        return len(_api_collect_results(token, "event-follows/"))
    except Exception:
        return 0


def _get_last_order(token: str):
    """Recupera l'ultimo ordine completato (biglietto acquistato)."""
    try:
        data = _api_request(
            "GET", 
            "my/purchases/", 
            params={"page": 1, "page_size": 1, "ordering": "-created_at"},
            token=token,
            timeout=10
        ) or {}
        rows = data.get("results", [])
        if not rows:
            return None
        
        order = rows[0]
        listing = (order.get("listing_info") or {})
        perf = (listing.get("performance_info") or {})
        
        return {
            "id": order.get("id"),
            "event_title": perf.get("evento_nome") or "Evento",
            "venue": perf.get("luogo_nome") or "",
            "starts_fmt": _fmt_iso_dmy_hm(perf.get("starts_at_utc") or ""),
            "created_fmt": _fmt_iso_dmy_hm(order.get("created_at") or ""),
            "total": order.get("total"),
            "currency": order.get("currency") or "EUR",
        }
    except Exception:
        return None


def _get_active_subscriptions_count(token: str) -> int:
    """Conta gli abbonamenti PRO attivi dell'utente."""
    try:
        rows = _api_collect_results(token, "monitoraggi/my-pro/")
        # Conta solo i monitoraggi con status "Attivo"
        count = 0
        for m in rows:
            status = _map_sub_status(m)
            if status == "Attivo":
                count += 1
        return count
    except Exception:
        return 0


def _get_my_listings_available_count(token: str) -> int:
    """
    Conta i biglietti in vendita non ancora venduti dell'utente.
    Somma tutte le quantità disponibili (qty - sold_qty) dai listing attivi.
    """
    try:
        rows = _api_collect_results(token, "my/resales/")
        total_available = 0
        for listing in rows:
            qty = int(listing.get("qty") or 0)
            sold_qty = int(listing.get("sold_qty") or 0)
            available = qty - sold_qty
            if available > 0:
                total_available += available
        return total_available
    except Exception:
        return 0


def account_admin(request):
    # login obbligatorio ma rispetta il "next"
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)

    # Profilo (opzionale)
    profilo = {}
    try:
        profilo = api_get_profile(token) or {}
    except Exception:
        profilo = {}

    # === SOLO LETTURA per /account/ ===
    active_alerts = _get_active_alerts(token)          # elenco con scadenza
    # Derivati dalla stessa sorgente della tabella dashboard: evita disallineamenti.
    free_alerts_count = sum(1 for a in active_alerts if (a.get("type") or "").lower() == "free")
    active_subscriptions_count = sum(1 for a in active_alerts if (a.get("type") or "").lower() == "pro")
    last_ticket = _get_last_order(token)               # ultimo ordine pagato
    my_listings_available = _get_my_listings_available_count(token)  # biglietti in vendita

    ctx = {
        "profilo": profilo,
        "active_alerts": active_alerts,
        "free_alerts_count": free_alerts_count,
        "active_subscriptions_count": active_subscriptions_count,
        "last_ticket": last_ticket,
        "my_listings_available": my_listings_available,
    }
    return render(request, "web/admin.html", ctx)


# =========================
# Pagina “Top venditori” (VIEW ALL) con paginazione
# =========================
def top(request):
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except Exception:
        page = 1
    per_page = 40
    offset = (page - 1) * per_page

    base = settings.API_BASE_URL.rstrip("/")
    data, rows = {"count": 0, "results": []}, []

    # A) endpoint dedicato
    try:
        resp = requests.get(f"{base}/listings/top/", params={"limit": per_page, "offset": offset}, timeout=8)
        resp.raise_for_status()
        data = resp.json() or {}
        rows = data.get("results", data if isinstance(data, list) else []) or []
    except Exception:
        rows = []

    # B) fallback /listings/?is_top=true
    if not rows:
        try:
            resp = requests.get(
                f"{base}/listings/",
                params={"limit": per_page, "offset": offset, "is_top": "true"},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            rows = data.get("results", data if isinstance(data, list) else []) or []
        except Exception:
            rows = []

    # C) fallback temporaneo: usa performances se non ci sono listing
    if not rows:
        try:
            resp = requests.get(
                f"{base}/search/performances/",
                params={"limit": per_page, "page": page, "ordering": "starts_at_utc"},
                timeout=8,
            )
            resp.raise_for_status()
            perf_data = resp.json() or {}
            perf_rows = perf_data.get("results", perf_data if isinstance(perf_data, list) else []) or []

            synthetic_rows = []
            for p in perf_rows:
                if not isinstance(p, dict):
                    continue
                synthetic_rows.append({
                    "id": f"perf-{p.get('id')}",
                    "performance_info": {
                        "id": p.get("id"),
                        "evento_nome": p.get("evento_nome") or "Evento",
                        "luogo_nome": p.get("luogo_nome") or "",
                        "starts_at_utc": p.get("starts_at_utc") or "",
                    },
                    "seller_info": {
                        "first_name": "Tixy",
                        "last_name": "Network",
                    },
                    "qty": 1,
                    "price_each": p.get("prezzo_min") or p.get("prezzo_max") or 0,
                    "delivery_method": "digitale",
                    "is_top": True,
                })

            rows = synthetic_rows
            data = {
                "count": int(perf_data.get("count") or len(rows)),
                "results": rows,
            }
        except Exception:
            rows = []

    # D) fallback FE: filtro client-side
    def _is_top(it):
        it = it or {}
        return bool(
            it.get("is_top")
            or it.get("top")
            or str(it.get("badge") or "").lower() == "top"
            or ("tags" in it and "top" in [str(t).lower() for t in (it.get("tags") or [])])
        )
    if rows and isinstance(rows, list) and not any(("is_top" in r or "top" in r) for r in rows):
        rows = [r for r in rows if _is_top(r)]

    # normalizzazione per il template
    items = []
    for it in rows:
        it = it or {}
        perf = (it.get("performance_info") or {})
        seller = (it.get("seller_info") or {})
        iso = perf.get("starts_at_utc") or ""
        dm = (it.get("delivery_method") or "")
        try:
            price_each = float(it.get("price_each") or 0)
        except Exception:
            price_each = 0.0

        items.append({
            **it,
            "perf_id": perf.get("id"),
            "starts_fmt": _fmt_iso_dmy_hm(iso),
            "delivery_method_label": dm.replace("_", " ").upper() if dm else "",
            "price_each": price_each,
        })

    count = int(data.get("count") or len(items))
    pages = max(1, ceil(count / per_page))

    ctx = {
        "items": items,
        "count": count,
        "page": page,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }
    return render(request, "web/top.html", ctx)


# =========================
# Riepilogo ordine con commissione 10% + cambio nominativo
# =========================
def order_summary_view(request, order_id: int):
    email = request.session.get("checkout_email") or request.GET.get("email")
    try:
        order = checkout_summary(order_id, email=email)
    except Exception as e:
        messages.error(request, f"Non riesco a caricare il riepilogo: {e}")
        return redirect("home")

    qty        = int(order.get("qty") or 1)
    unit_price = D(order.get("unit_price") or (order.get("listing_info") or {}).get("price_each"))
    subtotal_api   = D(order.get("subtotal"))
    commission_api = D(order.get("commission"))
    total_api      = D(order.get("total"))

    subtotal   = subtotal_api if subtotal_api > 0 else (unit_price * qty).quantize(Decimal("0.01"))
    commission = commission_api if commission_api > 0 else (subtotal * Decimal("0.10")).quantize(Decimal("0.01"))
    base_total = total_api if total_api > 0 else (subtotal + commission).quantize(Decimal("0.01"))

    perf = (order.get("listing_info") or {}).get("performance_info") or {}
    starts_iso = perf.get("starts_at_utc") or perf.get("starts_at") or ""
    perf_when = _fmt_iso_dmy_hm(starts_iso)
    change_fee, change_msg, change_required = calc_change_name_fee(starts_iso)
    final_total = (base_total + change_fee).quantize(Decimal("0.01"))

    ctx = {
        "order": order,
        "perf_when": perf_when,
        "subtotal": subtotal,
        "commission": commission,
        "change_fee": change_fee,
        "change_msg": change_msg,
        "change_required": change_required,
        "final_total": final_total,
    }
    return render(request, "web/order_summary.html", ctx)


def events_index(request):
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except Exception:
        page = 1

    per_page = 21  # <-- quello che vuoi vedere SEMPRE
    sort = request.GET.get("sort", "date_asc")
    if sort == "date_asc":
        ordering = "starts_at_utc"
    elif sort == "date_desc":
        ordering = "-starts_at_utc"
    elif sort == "az":
        ordering = "evento_nome"
    elif sort == "za":
        ordering = "-evento_nome"
    else:
        ordering = "starts_at_utc"

    now_utc = datetime.now(dt_timezone.utc)

    # Raccoglie TUTTI gli eventi futuri disponibili per calcolare correttamente il numero di pagine
    collected = []

    api_page = 1
    max_api_pages = 100  # safety - aumentato per gestire più eventi
    api_page_size = 100  # chiediamo più righe per volta per essere più efficiente

    while api_page <= max_api_pages:
        data = {}
        try:
            data = search_performances(
                q=None, date=None, city=None,
                page=api_page,
                ordering=ordering,
                page_size=api_page_size
            ) or {}
        except Exception:
            break

        raw = data.get("results", data if isinstance(data, list) else []) or []
        if not raw:
            break

        for it in raw:
            if not isinstance(it, dict):
                continue

            iso = (it.get("starts_at_utc") or
                   (it.get("performance_info") or {}).get("starts_at_utc") or "")
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=dt_timezone.utc)
            except Exception:
                continue

            if dt <= now_utc:
                continue

            evento_nome = (it.get("evento_nome") or (it.get("performance_info") or {}).get("evento_nome") or "").strip()
            luogo_nome  = (it.get("luogo_nome")  or (it.get("performance_info") or {}).get("luogo_nome")  or "").strip()
            perf_id     = it.get("id") or it.get("performance")

            collected.append({
                "perf_id": perf_id,
                "evento_nome": evento_nome,
                "luogo_nome": luogo_nome,
                "starts_iso": iso,
                "starts_fmt": _fmt_iso_dmy_hm(iso),
            })

        # se l'API ha next=None puoi anche interrompere qui:
        if isinstance(data, dict) and not data.get("next"):
            break

        api_page += 1

    # ordina secondo filtro scelto
    if sort == "date_asc":
        collected.sort(key=lambda x: x.get("starts_iso") or "")
    elif sort == "date_desc":
        collected.sort(key=lambda x: x.get("starts_iso") or "", reverse=True)
    elif sort == "az":
        collected.sort(key=lambda x: (x.get("evento_nome") or "").lower())
    elif sort == "za":
        collected.sort(key=lambda x: (x.get("evento_nome") or "").lower(), reverse=True)
    else:
        collected.sort(key=lambda x: x.get("starts_iso") or "")

    total = len(collected)  # totale “che abbiamo visto” (stima FE)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = collected[start:end]

    pages = max(1, ceil(total / per_page))

    return render(request, "web/events_index.html", {
        "items": page_items,
        "count": total,
        "page": page,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    })



def _fetch_event_performances_any(event_id: int):
    """
    Prova a recuperare le performances di un evento con più strategie,
    perché i backend spesso espongono endpoint/parametri diversi.
    Ritorna una lista di dict (performances grezze) oppure [].
    """
    attempts = [
        # endpoint, params
        ("performances/", {"evento": event_id, "ordering": "starts_at_utc", "limit": 200}),
        ("performances/", {"event": event_id, "ordering": "starts_at_utc", "limit": 200}),
        ("performances/", {"evento_id": event_id, "ordering": "starts_at_utc", "limit": 200}),
        ("search/performances/", {"evento": event_id, "ordering": "starts_at_utc", "limit": 200}),
        ("search/performances/", {"event": event_id, "ordering": "starts_at_utc", "limit": 200}),
        ("search/performances/", {"evento_id": event_id, "ordering": "starts_at_utc", "limit": 200}),
    ]

    for ep, params in attempts:
        try:
            data = _api_request("GET", ep, params=params) or {}
            rows = data.get("results", data if isinstance(data, list) else []) or []
            # se torna qualcosa, stop
            if rows:
                return rows
        except Exception:
            continue

    return []

def event_dates(request, event_id: int):
    """
    Elenca tutte le date (performance) future per un dato EVENTO.
    Mostra una "data principale" + elenco "altre date".
    """
    if not event_id:
        messages.error(request, "Evento non valido.")
        return redirect("home")

    evento = {}
    performances = []
    error = None

    try:
        evento = get_event(event_id) or {}

        perf_list = (
            evento.get("performances")
            or evento.get("performance_set")
            or []
        )

        # Caso 1: performances nel dettaglio evento ma come ID (lista di int/string)
        # → proviamo a trasformarle in dict chiamando get_performance(id)
        if perf_list and all(isinstance(x, (int, str)) for x in perf_list):
            tmp = []
            for pid in perf_list[:200]:
                try:
                    tmp.append(get_performance(int(pid)))
                except Exception:
                    pass
            perf_list = tmp

        # Caso 2: nessuna performance nel dettaglio evento → fallback API performances
        if not perf_list:
            perf_list = _fetch_event_performances_any(event_id)

        # Caso 3: fallback finale (la tua ricerca per nome) se ancora vuoto
        if not perf_list:
            nome_evento = (
                (evento.get("nome_evento") or "")
                or (evento.get("nome") or "")
                or (evento.get("title") or "")
            ).strip()

            if nome_evento:
                data = search_performances(q=nome_evento)
                raw = data.get("results", data if isinstance(data, list) else []) if data else []
                # filtra per event_id
                perf_list = [
                    p for p in raw
                    if str((p.get("evento") or p.get("event") or p.get("evento_id")
                            or (p.get("performance_info") or {}).get("evento")
                            or (p.get("performance_info") or {}).get("event")
                            or (p.get("performance_info") or {}).get("evento_id")
                            )) == str(event_id)
                ]

        now_utc = datetime.now(dt_timezone.utc)
        norm = []

        for p in perf_list:
            # normalizza: a volte arriva come {"performance_info": {...}} o direttamente {...}
            perf = p.get("performance_info") if isinstance(p, dict) and "performance_info" in p else p
            perf = perf or {}

            perf_id = perf.get("id") or (p.get("id") if isinstance(p, dict) else None)
            iso = perf.get("starts_at_utc") or perf.get("starts_at") or ""

            # tieni solo future
            keep = True
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=dt_timezone.utc)
                keep = dt >= now_utc
            except Exception:
                # se non parsabile, la teniamo (meglio mostrarla che perdere tutto)
                keep = True

            if keep and perf_id:
                norm.append({
                    "id": int(perf_id),
                    "evento_nome": (
                        perf.get("evento_nome")
                        or evento.get("nome_evento")
                        or evento.get("nome")
                        or evento.get("title")
                        or ""
                    ),
                    "luogo_nome": (
                        perf.get("luogo_nome")
                        or perf.get("venue")
                        or evento.get("luogo_nome")
                        or ""
                    ),
                    "starts_iso": iso,
                    "starts_fmt": _fmt_iso_dmy_hm(iso),
                })

        norm.sort(key=lambda x: (x["starts_iso"] or ""))
        performances = norm

    except Exception as e:
        error = str(e)

    # separa "prima data" e "altre date"
    main_date = performances[0] if performances else None
    other_dates = performances[1:] if len(performances) > 1 else []

    return render(request, "web/event_dates.html", {
        "event_id": event_id,
        "evento": evento or {},
        "main_date": main_date,
        "other_dates": other_dates,
        "items": performances,  # compat (se nel template usi ancora items)
        "error": error,
        "count": len(performances),
    })


def event_dates_from_perf(request, perf_id: int):
    """
    Ponte: dato perf_id, ricava event_id dalla performance e redirecta a /evento/<event_id>/date/
    """
    try:
        perf = get_performance(perf_id) or {}

    except Exception:
        return HttpResponseNotFound("Performance non trovata.")

    event_id = perf.get("evento") or perf.get("event") or perf.get("evento_id")
    if not event_id:
        return HttpResponseNotFound("Evento non disponibile per questa performance.")

    return redirect(reverse("event_dates", args=[int(event_id)]))


def rivenditori(request):
    """
    Elenco completo rivenditori (dedupe=seller) con paginazione.
    Ogni card mostra un listing rappresentativo del venditore.
    """
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except Exception:
        page = 1
    per_page = 36
    offset = (page - 1) * per_page

    base = settings.API_BASE_URL.rstrip("/")
    data = {"count": 0, "results": []}
    try:
        resp = requests.get(
            f"{base}/listings/",
            params={
                "limit": per_page,
                "offset": offset,
                "dedupe": "seller",
                "ordering": "-seller_rating",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json() or {"count": 0, "results": []}
    except Exception:
        pass

    items = data.get("results", []) or []

    for it in items:
        perf = (it or {}).get("performance_info") or {}
        seller = (it or {}).get("seller_info") or {}
        iso = perf.get("starts_at_utc") or ""
        it["starts_fmt"] = _fmt_iso_dmy_hm(iso)
        it["perf_name"] = perf.get("evento_nome") or ""
        it["venue"] = perf.get("luogo_nome") or ""
        it["seller_name"] = f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip() or f"Venditore #{it.get('seller')}"
        dm = (it or {}).get("delivery_method") or ""
        it["delivery_method_label"] = dm.replace("_", " ").upper() if dm else ""
        try:
            it["price_each"] = float(it.get("price_each") or 0)
        except Exception:
            it["price_each"] = 0.0

    count = int(data.get("count") or 0)
    pages = max(1, ceil(count / per_page))

    ctx = {
        "items": items,
        "count": count,
        "page": page,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }
    return render(request, "web/rivenditori.html", ctx)


def rivendita(request):
    """
    Elenco pubblico degli annunci di rivendita attivi (usa /listings/).
    """
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except Exception:
        page = 1

    per_page = 36
    offset = (page - 1) * per_page

    raw = []
    try:
        data = _api_request(
            "GET", "listings/",
            params={"limit": per_page, "offset": offset, "status": "ACTIVE", "ordering": "-created_at"},
        ) or {}
        raw = data.get("results", data if isinstance(data, list) else []) or []
        total = int(data.get("count") or len(raw))
    except Exception:
        raw = []
        total = 0

    items = []
    for r in raw:
        qty = int(r.get("qty") or 0)
        if qty <= 0:
            continue

        perf = (r.get("performance_info") or {})
        seller = (r.get("seller_info") or {})
        seller_name = (
            seller.get("display_name")
            or f"{(seller.get('first_name') or '').strip()} {(seller.get('last_name') or '').strip()}".strip()
            or f"Venditore #{r.get('seller')}"
        )

        try:
            price_each = float(r.get("price_each") or 0)
        except Exception:
            price_each = 0.0

        total_price = price_each * qty

        # subitems pubblici
        subitems_raw = r.get("public_subitems") or []
        subitems = [
            {
                "full_name": s.get("full_name") or s.get("name") or "",
                "code_type": s.get("code_type") or "CODE",
                "code_value": s.get("code_value") or s.get("barcode") or "—",
                "price": s.get("face_value") or s.get("price") or "",
            }
            for s in subitems_raw
        ]

        items.append({
            "id": r.get("id"),
            "seller": r.get("seller"),
            "seller_name": seller_name,
            "rating": r.get("seller_rating_avg"),
            "reviews": r.get("seller_reviews_count"),
            "qty": qty,
            "price_each": price_each,
            "total_price": total_price,
            "currency": r.get("currency") or "EUR",
            "delivery_method": r.get("delivery_method") or "",
            "notes": r.get("notes") or "",
            "perf_name": perf.get("evento_nome") or "Evento",
            "venue": perf.get("luogo_nome") or "",
            "starts_fmt": _fmt_iso_dmy_hm(perf.get("starts_at_utc") or perf.get("starts_at") or ""),
            "subitems": subitems,
        })

    pages = max(1, ceil(total / per_page))

    ctx = {
        "items": items,
        "count": total,
        "page": page,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }
    return render(request, "web/rivendita.html", ctx)


#abbonamenti area riservata


def _map_sub_status(item: dict) -> str:
    """
    Stati: Attivo | Scaduto | Chiuso
    """
    it = item or {}
    status_raw = (it.get("status") or it.get("stato") or "").lower().strip()

    # Se l'API ci passa gia un'etichetta "umana", normalizziamo eventuali Pending/Pedding ad Attivo.
    if it.get("status_label"):
        label = str(it["status_label"]).strip().lower()
        if label in ("pending", "pedding"):
            return "Attivo"
        if label in ("active", "attivo"):
            return "Attivo"
        if label in ("expired", "scaduto"):
            return "Scaduto"
        if label in ("closed", "chiuso"):
            return "Chiuso"
        return str(it["status_label"])

    # my-pro flat: status="active"
    if status_raw in ("active", "attivo"):
        return "Attivo"

    expires = _safe_dt(it.get("expires_at") or it.get("scade_il") or it.get("valid_until"))
    done_at = _safe_dt(it.get("done_at") or it.get("success_at") or it.get("notified_at"))

    # date evento (da evento o performance)
    ev = it.get("evento_info") or it.get("event_info") or {}
    perf = it.get("performance_info") or {}
    event_dt = _safe_dt(ev.get("starts_at_utc") or ev.get("starts_at") or perf.get("starts_at_utc"))

    now = datetime.utcnow().replace(tzinfo=dt_timezone.utc)

    if event_dt and event_dt < now:
        return "Chiuso"
    if expires and expires < now:
        return "Scaduto"
    # se c'e un esito "ok", lo consideriamo ancora attivo fino a scadenza/evento
    if done_at or status_raw in ("success", "trovato", "completed", "ok"):
        return "Attivo"
    return "Attivo"



def _api_subscriptions_list(token: str, page: int = 1, per_page: int = 20):
    """
    Legge gli abbonamenti/monitoraggi PRO dell'utente (endpoint my-pro).
    Ritorna (items, total) con campi raw + formattati.
    """
    data = _api_request(
        "GET",
        "monitoraggi/my-pro/",
        params={"page": page, "page_size": per_page},
        token=token
    ) or {}

    rows = data.get("results", data if isinstance(data, list) else []) or []
    items = []

    for r in rows:
        ev = (r.get("evento_info") or r.get("event_info") or {})
        perf = (r.get("performance_info") or {})

        # NUOVI CAMPI (my-pro "piatto") + fallback ai vecchi
        title = r.get("event_title") or r.get("title") or ev.get("nome") or ev.get("title") or "Evento"
        created_iso = r.get("activated_at") or r.get("created_at") or r.get("creato_il") or r.get(
            "abbonamento_created_at") or ""
        expires_iso = r.get("expires_at") or r.get("scade_il") or r.get("valid_until") or ""
        event_iso = (
                r.get("event_date")  # my-pro flat
                or ev.get("starts_at_utc") or ev.get("starts_at")
                or perf.get("starts_at_utc")
                or ""
        )

        item = {
            "id": r.get("id"),
            "title": title,
            "cover": ev.get("cover_url") or None,

            # RAW
            "created_at_iso": created_iso,
            "expires_at_iso": expires_iso,
            "event_date_iso": event_iso,

            # FORMATTATI
            "created_at": _fmt_iso_dmy_hm(created_iso),
            "expires_at": _fmt_iso_dmy_hm(expires_iso),
            "event_date": _fmt_iso_dmy_hm(event_iso),

            "status": _map_sub_status(r),
            "period": r.get("period_label") or r.get("durata_label") or "",
        }

        items.append(item)

    total = int(data.get("count") or len(items))
    return items, total



def account_subscriptions_view(request):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    page = max(1, int(request.GET.get("page", 1)))
    per_page = 12

    items, total = _api_subscriptions_list(token, page=page, per_page=per_page)
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(1)  # l'API è già paginata

    return render(request, "web/account/subscriptions.html", {
        "page_obj": page_obj,
        "total": total,
    })


# =========================
# Account: I miei biglietti (acquisti)
# =========================
def account_tickets_view(request):
    """
    Elenco dei biglietti acquistati:
    - default: solo NON scaduti (eventi futuri)
    - ?past=1 per vedere lo STORICO (eventi passati)
    - ordinati DESC per data di creazione ordine
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except Exception:
        page = 1
    per_page = 12
    show_past = request.GET.get("past") in ("1", "true", "yes")

    # Chiamiamo l’endpoint API /my/purchases/ già predisposto lato backend
    params = {
        "page": page,
        "page_size": per_page,
        "ordering": "-created_at",
        "past": "1" if show_past else None,
    }
    # rimuovi None
    params = {k: v for k, v in params.items() if v is not None}

    data = {"results": [], "count": 0}
    try:
        data = _api_request("GET", "my/purchases/", params=params, token=token) or {}
    except Exception as e:
        messages.error(request, f"Impossibile caricare i biglietti: {e}")
        data = {"results": [], "count": 0}

    rows = data.get("results", data if isinstance(data, list) else []) or []
    total = int(data.get("count") or len(rows))

    # Normalizzazione per il template
    items = []
    for r in rows:
        # L'API /my/purchases/ restituisce campi piatti (flat)
        # Manteniamo anche fallback per strutture nested legacy
        listing = (r.get("listing_info") or r.get("listing") or {}) or {}
        perf    = (listing.get("performance_info") or r.get("performance_info") or {}) or {}

        order_id    = r.get("id") or r.get("order_id")
        created_iso = r.get("created_at") or r.get("paid_at") or r.get("delivered_at") or ""
        starts_iso  = (
            r.get("performance_datetime") or
            perf.get("starts_at_utc") or perf.get("starts_at") or ""
        )
        event_title = (
            r.get("event_title") or
            perf.get("evento_nome") or perf.get("title") or
            listing.get("title") or "Evento"
        )
        venue = (
            r.get("venue") or
            perf.get("luogo_nome") or perf.get("venue") or ""
        )
        qty = r.get("qty") or 1
        total_price = r.get("price_total") or r.get("total") or r.get("total_price") or listing.get("price_each")
        currency = r.get("currency") or listing.get("currency") or "EUR"

        # URL download: usa quello dell’API se presente, altrimenti passa dal proxy FE
        api_download = (
            r.get("download_url") or r.get("download") or r.get("ticket_url")
        )
        if api_download:
            download_href = reverse("ticket_download_proxy", args=[order_id])
        else:
            # fallback: l’API espone l’action /orders/{id}/download/
            download_href = reverse("ticket_download_proxy", args=[order_id])

        items.append({
            "order_id": order_id,
            "created_iso": created_iso,
            "created_fmt": _fmt_iso_dmy_hm(created_iso),
            "event_title": event_title,
            "venue": venue,
            "starts_iso": starts_iso,
            "starts_fmt": _fmt_iso_dmy_hm(starts_iso),
            "qty": qty,
            "total": total_price,
            "currency": currency,
            "download_href": download_href,
        })

    # Paginazione FE basata su total/per_page (l’API è già paginata, ma manteniamo coerenza UI)
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(1)  # mostriamo la pagina restituita dall'API come singola pagina UI

    ctx = {
        "page_obj": page_obj,
        "total": total,
        "show_past": show_past,  # per evidenziare il tab attivo
    }
    return render(request, "web/account/tickets.html", ctx)


# =========================
# Proxy di download del biglietto (PDF)
# =========================
def ticket_download_proxy(request, order_id: int):
    """
    Scarica il PDF del biglietto passando il bearer token lato server.
    Redirigere direttamente all’endpoint /orders/{id}/download/ del backend.
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    base = settings.API_BASE_URL.rstrip("/")

    # endpoint action backend
    url = f"{base}/orders/{order_id}/download/"

    try:
        # stream=True per passare il file così com'è
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=20)
        if r.status_code == 404:
            return HttpResponseNotFound("Biglietto non trovato.")
        r.raise_for_status()

        # prova a ricavare il filename dal Content-Disposition dell’API
        disp = r.headers.get("Content-Disposition") or ""
        filename = None
        if "filename=" in disp:
            filename = disp.split("filename=", 1)[1].strip('"; ')

        filename = filename or f"biglietto_{order_id}.pdf"
        resp = HttpResponse(r.content, content_type=r.headers.get("Content-Type", "application/pdf"))
        resp["Content-Disposition"] = f'attachment; filename="{quote(filename)}"'
        return resp

    except requests.HTTPError as e:
        return HttpResponseBadRequest(f"Impossibile scaricare il biglietto: {e}")
    except Exception:
        return HttpResponseBadRequest("Errore durante il download del biglietto.")

@require_http_methods(["GET", "POST"])
def account_resales_view(request):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard: return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    page = max(1, int(request.GET.get("page") or 1))
    per_page = 12
    selected_performance = (request.POST.get("performance") or request.GET.get("performance") or "").strip()
    open_edit_listing_id = (request.GET.get("edit_listing") or "").strip()

    perf_rows = []
    try:
        perf_data = _api_request(
            "GET",
            "search/performances/",
            params={"ordering": "starts_at_utc", "limit": 200},
            token=token,
            timeout=15,
        ) or {}
        perf_rows = perf_data.get("results", perf_data if isinstance(perf_data, list) else []) or []
    except Exception:
        perf_rows = []

    now = datetime.now(dt_timezone.utc)
    perfs = []
    for perf in perf_rows:
        if not isinstance(perf, dict):
            continue
        starts_iso = perf.get("starts_at_utc") or perf.get("starts_at") or ""
        starts_dt = _parse_iso_z(starts_iso)
        if starts_dt and starts_dt < now:
            continue
        perf_id = perf.get("id")
        if not perf_id:
            continue
        perfs.append({
            "id": perf_id,
            "evento": perf.get("evento_nome") or perf.get("event_name") or "Evento",
            "venue": perf.get("luogo_nome") or perf.get("venue_name") or "Luogo",
            "when_fmt": _fmt_iso_dmy_hm(starts_iso),
        })

    if request.method == "POST" and (request.POST.get("action") == "update_listing_selection"):
        listing_id = (request.POST.get("listing_id") or "").strip()
        selected_ids = request.POST.getlist("subitem_ids")
        redirect_url = reverse("account_resales")
        if listing_id:
            redirect_url = f"{redirect_url}?edit_listing={listing_id}#listing-{listing_id}"

        if not listing_id:
            messages.error(request, "Annuncio non trovato.")
            return redirect("account_resales")
        if not selected_ids:
            messages.error(request, "Seleziona almeno un biglietto da lasciare in vendita.")
            return redirect(redirect_url)

        try:
            _api_request(
                "POST",
                f"listings/{int(listing_id)}/update-selection/",
                json={"subitem_ids": list(map(int, selected_ids))},
                token=token,
                timeout=30,
            )
            messages.success(request, "Annuncio aggiornato con il nuovo numero di biglietti in vendita.")
            return redirect("account_resales")
        except Exception as e:
            messages.error(request, f"Impossibile aggiornare l'annuncio: {e}")
            return redirect(redirect_url)

    if request.method == "POST":
        performance_id = (request.POST.get("performance") or "").strip()
        ticket_url = (request.POST.get("ticket_url") or "").strip()
        file_obj = request.FILES.get("ticket_file")

        if not (file_obj or ticket_url):
            messages.error(request, "Carica un PDF oppure inserisci l'URL dell'e-ticket.")
            return redirect("account_resales")

        try:
            if file_obj:
                files = {"path_file": (file_obj.name, file_obj.read(), file_obj.content_type or "application/pdf")}
                payload = {}
                if performance_id:
                    payload["performance"] = performance_id
                out = _api_request(
                    "POST",
                    "ticket-uploads/pdf/",
                    data=payload,
                    files=files,
                    token=token,
                    timeout=120,
                ) or {}
            else:
                payload = {"url": ticket_url}
                if performance_id:
                    payload["performance"] = int(performance_id)
                out = _api_request(
                    "POST",
                    "ticket-uploads/url/",
                    json=payload,
                    token=token,
                    timeout=120,
                ) or {}

            upload_id = out.get("upload_id")
            if not upload_id:
                messages.error(request, "Upload avviato ma non e stato restituito un identificativo.")
                return redirect("account_resales")
            return redirect("resales_upload_review", upload_id=upload_id)
        except requests.HTTPError as e:
            messages.error(request, f"Biglietto non valido o modificato: {e}")
            return redirect("account_resales")
        except Exception as e:
            messages.error(request, f"Errore durante il caricamento: {e}")
            return redirect("account_resales")

    # chiama l’endpoint backend già presente (TicketUploadViewSet/MyResalesView)
    try:
        data = _api_request("GET", "my/resales/", params={
            "page": page, "page_size": per_page, "ordering": "-created_at"
        }, token=token) or {}
    except Exception as e:
        messages.error(request, f"Impossibile caricare le rivendite: {e}")
        data = {"results": [], "count": 0}

    rows = data.get("results", []) or []
    items = []
    for r in rows:
        perf = (r.get("performance_info") or {})
        starts_iso = perf.get("starts_at_utc") or perf.get("starts_at") or ""
        # stato venduto
        sold_qty = int(r.get("sold_qty") or 0)
        qty = int(r.get("qty") or 0)
        status_value = (r.get("status") or "").upper()
        is_sold = status_value == "SOLD" or qty <= 0

        # download PDF (se presente)
        download_url = r.get("download_url")

        items.append({
            "id": r.get("id"),
            "created_fmt": _fmt_iso_dmy_hm(r.get("created_at") or ""),
            "price_each": r.get("price_each"),
            "currency": r.get("currency") or "EUR",
            "status": status_value,
            "qty": qty,
            "sold_qty": sold_qty,
            "is_sold": is_sold,
            "notes": r.get("notes") or "",
            "perf_name": (perf.get("evento_nome") or ""),
            "venue": (perf.get("luogo_nome") or ""),
            "starts_fmt": _fmt_iso_dmy_hm(starts_iso),
            "download_url": download_url,  # può essere None
            "selected_subitem_ids": [str(x) for x in (r.get("selected_subitem_ids") or [])],
            "editable_subitems": r.get("editable_subitems") or [],
            "is_edit_open": str(r.get("id")) == open_edit_listing_id,
        })

    return render(request, "web/account/resales.html", {
        "items": items,
        "count": int(data.get("count") or len(items)),
        "page": page,
        "page_size": per_page,
        "perfs": perfs,
        "selected_performance": selected_performance,
        "open_edit_listing_id": open_edit_listing_id,
    })




@require_http_methods(["GET", "POST"])
def resales_upload(request):
    return redirect("account_resales")


@require_http_methods(["GET","POST"])
def resales_upload_review_view(request, upload_id: int):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard: return guard
    token = request.session.get(SESSION_TOKEN_KEY)
    # GET -> recupera review
    try:
        review = _api_request("GET", f"ticket-uploads/{upload_id}/review/", token=token) or {}
    except Exception as e:
        messages.error(request, f"Impossibile leggere i dettagli upload: {e}")
        return redirect("account_resales")

    # subitems per tabella
    subs = review.get("subitems") or []
    big = review.get("biglietto_info") or {}
    if big.get("event_date_iso"):
        big["event_date_fmt"] = _fmt_iso_dmy_hm(big.get("event_date_iso") or "")
    else:
        big["event_date_fmt"] = ""
    status_value = review.get("status") or ""

    if status_value == "ERROR":
        messages.error(request, review.get("error_message") or "Il biglietto risulta modificato o non valido.")
        return redirect("account_resales")

    performance_info = big.get("performance") or {}
    performance_id = performance_info.get("id")
    selected_ids = []
    selected_items = []
    step = "select"
    price_each = request.POST.get("price_each") or ""
    currency = request.POST.get("currency") or "EUR"
    delivery = request.POST.get("delivery_method") or (big.get("source_kind") or "PDF")
    notes = request.POST.get("notes") or ""
    boost = request.POST.get("boost") in ("1", "true", "on")
    accept_listing = request.POST.get("accept_listing") in ("1", "true", "on")

    def _find_selected_items(ids):
        idset = {str(x) for x in ids}
        return [s for s in subs if str(s.get("id")) in idset]

    if request.method == "POST":
        step = request.POST.get("step") or "select"
        selected_ids = request.POST.getlist("subitem_ids")
        selected_items = _find_selected_items(selected_ids)

        if step == "select":
            if not selected_items:
                messages.error(request, "Seleziona almeno un biglietto da mettere in vendita.")
                step = "select"
            else:
                step = "pricing"

        elif step == "pricing":
            if not selected_items:
                messages.error(request, "Seleziona almeno un biglietto da mettere in vendita.")
                step = "select"
            else:
                price_caps = []
                for item in selected_items:
                    raw_price = item.get("price")
                    if raw_price not in (None, ""):
                        try:
                            price_caps.append(Decimal(str(raw_price)))
                        except Exception:
                            pass
                max_allowed = (min(price_caps) - Decimal("0.50")) if price_caps else None
                try:
                    requested_price = Decimal(str(price_each))
                except Exception:
                    requested_price = None

                if requested_price is None or requested_price <= 0:
                    messages.error(request, "Inserisci un prezzo valido.")
                    step = "pricing"
                elif max_allowed is not None and requested_price > max_allowed:
                    messages.error(request, f"Il prezzo massimo consentito e {max_allowed:.2f} EUR.")
                    step = "pricing"
                else:
                    step = "recap"

        elif step == "confirm":
            if not selected_items:
                messages.error(request, "Seleziona almeno un biglietto da mettere in vendita.")
                step = "select"
            elif not accept_listing:
                messages.error(request, "Devi confermare il recap prima di mettere in vendita.")
                step = "recap"
            elif not performance_id:
                messages.error(request, "Performance non trovata per questo biglietto.")
                step = "select"
            else:
                try:
                    payload = {
                        "subitem_ids": list(map(int, selected_ids)),
                        "price_each": str(price_each),
                        "currency": currency,
                        "delivery_method": delivery,
                        "notes": notes,
                        "performance": int(performance_id),
                        "is_top": boost,
                    }
                    res = _api_request("POST", f"ticket-uploads/{upload_id}/confirm/", json=payload, token=token) or {}
                    if res.get("listing_id"):
                        messages.success(request, "Annuncio creato e messo in vendita.")
                        return redirect("account_resales")
                    messages.error(request, "Impossibile creare l'annuncio.")
                    step = "recap"
                except Exception as e:
                    messages.error(request, f"Errore durante la conferma: {e}")
                    step = "recap"

    price_caps = []
    for item in selected_items:
        raw_price = item.get("price")
        if raw_price not in (None, ""):
            try:
                price_caps.append(Decimal(str(raw_price)))
            except Exception:
                pass
    max_allowed = (min(price_caps) - Decimal("0.50")) if price_caps else None

    return render(request, "web/account/resales_upload_review.html", {
        "upload_id": upload_id,
        "biglietto": big,
        "subitems": subs,
        "step": step,
        "selected_ids": [str(x) for x in selected_ids],
        "selected_items": selected_items,
        "price_each": price_each,
        "currency": currency,
        "delivery_method": delivery,
        "notes": notes,
        "max_allowed_price": f"{max_allowed:.2f}" if max_allowed is not None else "",
        "performance_id": performance_id,
        "boost": boost,
    })

# =========================
# Account: Supporto (ticket)
# =========================

@require_http_methods(["GET"])
def account_support_list(request):
    """
    Elenco dei ticket dell'utente loggato, ordinati per data desc.
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    page = max(1, int(request.GET.get("page", 1)))
    per_page = 12

    data = {"results": [], "count": 0}
    try:
        data = _api_request(
            "GET",
            "support/tickets/",
            params={"page": page, "page_size": per_page, "ordering": "-created_at"},
            token=token,
            timeout=10,
        ) or {}
    except Exception as e:
        messages.error(request, f"Impossibile caricare i ticket: {e}")

    rows = data.get("results", []) or []
    count = int(data.get("count") or len(rows))

    # normalizza campi minimi per la lista
    items = []
    for t in rows:
        items.append({
            "id": t.get("id"),
            "title": (t.get("title") or "").strip() or f"Ticket #{t.get('id')}",
            "status": (t.get("status") or "").strip().title(),
            "priority": (t.get("priority") or "").strip().title(),
            "category": (t.get("category") or "").strip().title(),
            "created_fmt": _fmt_iso_dmy_hm(t.get("created_at") or ""),
            "updated_fmt": _fmt_iso_dmy_hm(t.get("updated_at") or ""),
        })

    # L'API è già paginata: mostriamo la pagina ricevuta come singola pagina UI
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(1)

    return render(request, "web/account/support_list.html", {
        "page_obj": page_obj,
        "count": count,
        "page": page,
    })




@require_http_methods(["GET", "POST"])
def account_support_new(request):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)

    # Solo per UI (non spediamo questi valori alle API)
    categories = [
        {"value": "generale",  "label": "Generale"},
        {"value": "pagamenti", "label": "Pagamenti"},
        {"value": "download",  "label": "Download biglietti"},
        {"value": "rivendita", "label": "Rivendita"},
        {"value": "altro",     "label": "Altro"},
    ]
    priorities = [
        {"value": "bassa",   "label": "Bassa"},
        {"value": "media",   "label": "Media"},
        {"value": "alta",    "label": "Alta"},
        {"value": "critica", "label": "Critica"},
    ]

    if request.method == "POST":
        title      = (request.POST.get("title") or "").strip()
        message_   = (request.POST.get("message") or "").strip()
        # UI only (non inviamo all'API)
        category_ui = (request.POST.get("category_ui") or "generale").strip()
        priority_ui = (request.POST.get("priority_ui") or "media").strip()
        order_id   = (request.POST.get("order_id") or "").strip()
        privacy    = bool(request.POST.get("privacy_ok"))

        # Validazioni lato FE
        if not title or not message_:
            messages.error(request, "Titolo e Messaggio sono obbligatori.")
            return render(request, "web/account/support_new.html", {
                "categories": categories, "priorities": priorities,
                "form": {"title": title, "message": message_, "category": category_ui,
                         "priority": priority_ui, "order_id": order_id, "privacy_ok": privacy}
            })
        if not privacy:
            messages.error(request, "Devi accettare la privacy per aprire un ticket.")
            return render(request, "web/account/support_new.html", {
                "categories": categories, "priorities": priorities,
                "form": {"title": title, "message": message_, "category": category_ui,
                         "priority": priority_ui, "order_id": order_id, "privacy_ok": privacy}
            })

        # Payload verso API: **NON** includiamo category/priority
        base_fields = {
            "title": title,
            "message": message_,
        }
        if order_id:
            # inviamo entrambe, nel dubbio
            base_fields["order"] = order_id
            base_fields["order_id"] = order_id

        uploaded_files = request.FILES.getlist("attachments") or []
        api_base = settings.API_BASE_URL.rstrip("/")
        url = f"{api_base}/support/tickets/"

        try:
            if uploaded_files:
                # multipart diretto con requests.post
                headers = {"Authorization": f"Bearer {token}"}
                files = []
                for f in uploaded_files:
                    files.append(("attachments", (f.name, f.read(), f.content_type or "application/octet-stream")))
                r = requests.post(url, headers=headers, data=base_fields, files=files, timeout=60)
                r.raise_for_status()
                res = r.json() if r.content else {}
            else:
                # JSON puro usando l'helper
                res = _api_request(
                    "POST",
                    "support/tickets/",
                    json=base_fields,
                    token=token,
                    timeout=60,
                )

            if isinstance(res, dict) and res.get("id"):
                messages.success(request, "✅ Ticket creato correttamente.")
                return redirect("account_support_detail", ticket_id=res["id"])

            msg = (res.get("detail") if isinstance(res, dict) else None) or "Impossibile creare il ticket."
            messages.error(request, msg)

        except requests.HTTPError as e:
            # Mostra gli errori del backend (se ci sono)
            try:
                err = e.response.json()
            except Exception:
                err = None

            if isinstance(err, dict) and err:
                # raccogli tutti i messaggi
                parts = []
                for k, v in err.items():
                    if isinstance(v, list):
                        parts.extend([str(x) for x in v])
                    else:
                        parts.append(str(v))
                messages.error(request, " ".join(parts) or f"Errore: {e}")
            else:
                messages.error(request, f"Errore: {e}")
        except Exception as e:
            messages.error(request, f"Errore imprevisto: {e}")
        return render(request, "web/account/support_new.html", {
            "categories": categories, "priorities": priorities,
            "form": {"title": title, "message": message_, "category": category_ui,
                     "priority": priority_ui, "order_id": order_id, "privacy_ok": privacy}
        })

    # GET
    return render(request, "web/account/support_new.html", {
        "categories": categories, "priorities": priorities,
        "form": {"title": "", "message": "", "category": "generale",
                 "priority": "media", "order_id": (request.GET.get("order") or ""), "privacy_ok": False}
    })

@require_http_methods(["GET", "POST"])
def account_support_detail(request, ticket_id: int):
    """
    Dettaglio ticket:
    - GET: mostra ticket + thread messaggi
    - POST: aggiungi risposta con eventuali allegati
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)

    # ============== POST: invio risposta ==================
    if request.method == "POST":
        body = (request.POST.get("body") or "").strip()
        if not body:
            messages.error(request, "Scrivi un messaggio.")
            return redirect(request.path)

        files = request.FILES.getlist("files") or request.FILES.getlist("files[]")
        try:
            if files:
                # multipart
                files_payload = [("files", (f.name, f.read(), f.content_type or "application/octet-stream")) for f in files]
                _api_request(
                    "POST",
                    f"support/tickets/{ticket_id}/messages/",
                    data={"body": body},   # campi testuali
                    files=files_payload,   # SOLO se la tua _api_request supporta 'files'
                    token=token,
                    timeout=60,
                )
            else:
                # JSON puro
                _api_request(
                    "POST",
                    f"support/tickets/{ticket_id}/messages/",
                    json={"body": body},
                    token=token,
                    timeout=60,
                )
            messages.success(request, "Messaggio inviato ✅")
            return redirect(request.path)
        except TypeError as e:
            # Se la tua _api_request NON supporta 'files', evita di passarlo
            messages.error(request, f"Errore invio (upload non supportato dall'helper): {e}")
            return redirect(request.path)
        except Exception as e:
            messages.error(request, f"Errore invio messaggio: {e}")
            return redirect(request.path)

    # ============== GET: dettaglio + messaggi ==============
    try:
        ticket = _api_request("GET", f"support/tickets/{ticket_id}/", token=token, timeout=10) or {}
        msgs_resp = _api_request("GET", f"support/tickets/{ticket_id}/messages/", token=token, timeout=10) or []
        messages_rows = msgs_resp if isinstance(msgs_resp, list) else (msgs_resp.get("results") or [])
    except Exception as e:
        messages.error(request, f"Impossibile caricare il ticket: {e}")
        return redirect("account_support_list")

    # normalizza messaggi per il template
    for m in messages_rows:
        m["created_fmt"] = _fmt_iso_dmy_hm(m.get("created_at") or "")

    # prova a ottenere una descrizione iniziale
    initial_msg = None
    if messages_rows:
        m0 = messages_rows[0] or {}
        initial_msg = m0.get("message") or m0.get("body") or m0.get("text")
    else:
        initial_msg = ticket.get("description") or ticket.get("message") or ticket.get("body")

    # label "umane"
    status_raw   = (ticket.get("status") or "").upper()
    priority_raw = (ticket.get("priority") or "").upper()
    category_raw = (ticket.get("category") or "").upper()

    STATUS_LABEL = {"OPEN": "Aperto", "PENDING": "In attesa", "CLOSED": "Chiuso"}
    PRIO_LABEL   = {"LOW": "Bassa", "NORMAL": "Media", "HIGH": "Alta", "CRITICAL": "Critica"}
    CAT_LABEL    = {
        "GENERAL": "Generale", "PAYMENTS": "Pagamenti", "DOWNLOAD": "Download biglietti",
        "RESALE": "Rivendita", "OTHER": "Other"
    }

    ctx = {
        "t": ticket,
        "msgs": messages_rows,

        "status_label": STATUS_LABEL.get(status_raw, status_raw.title() or "Open"),
        "priority_label": PRIO_LABEL.get(priority_raw, priority_raw.title() or "Media"),
        "category_label": CAT_LABEL.get(category_raw, category_raw.title() or "Other"),

        "created_fmt": _fmt_iso_dmy_hm(ticket.get("created_at") or ""),
        "updated_fmt": _fmt_iso_dmy_hm(ticket.get("updated_at") or ""),

        "order_id":    ticket.get("order")       or ticket.get("order_id"),
        "listing_id":  ticket.get("listing")     or ticket.get("listing_id"),
        "biglietto_id": ticket.get("biglietto")  or ticket.get("ticket_upload"),

        "description": initial_msg,
    }

    # alias per template (compat)
    ctx["ticket"] = ctx["t"]
    ctx["posts"]  = ctx["msgs"]

    return render(request, "web/account/support_detail.html", ctx)


@require_http_methods(["GET", "POST"])
def account_profile_view(request):
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)

    # ---- POST
    if request.method == "POST":
        action = request.POST.get("action") or ""
        try:
            if action == "update_profile":
                first_name = (request.POST.get("first_name") or "").strip()
                last_name  = (request.POST.get("last_name") or "").strip()
                phone_number = (request.POST.get("phone_number") or "").strip()
                marketing  = bool(request.POST.get("marketing_ok"))

                # --- NUOVI CAMPI SOCIAL
                facebook_url  = (request.POST.get("facebook_url") or "").strip()
                instagram_url = (request.POST.get("instagram_url") or "").strip()
                tiktok_url    = (request.POST.get("tiktok_url") or "").strip()
                x_url         = (request.POST.get("x_url") or "").strip()

                payload = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone_number": phone_number if phone_number else None,
                    "marketing_ok": marketing,

                    # social (chiavi allineate alle API) - invia None se vuoto
                    "facebook_url": facebook_url if facebook_url else None,
                    "instagram_url": instagram_url if instagram_url else None,
                    "tiktok_url": tiktok_url if tiktok_url else None,
                    "x_url": x_url if x_url else None,
                }

                print(f"DEBUG: Payload inviato: {payload}")  # DEBUG
                resp = _api_request("PATCH", "profile/", json=payload, token=token, timeout=15)
                print(f"DEBUG: Risposta API: {resp}")  # DEBUG
                messages.success(request, "Profilo aggiornato ✅")
                return redirect("account_profile")

            elif action == "change_password":
                old_pwd = request.POST.get("old_password") or ""
                new_pwd = request.POST.get("new_password") or ""
                rep_pwd = request.POST.get("new_password2") or ""
                if not old_pwd or not new_pwd or not rep_pwd:
                    messages.error(request, "Compila tutti i campi password.")
                    return redirect("account_profile")
                if new_pwd != rep_pwd:
                    messages.error(request, "Le nuove password non coincidono.")
                    return redirect("account_profile")

                _api_request(
                    "POST", "profile/change-password/",
                    json={"old_password": old_pwd, "new_password": new_pwd},
                    token=token, timeout=15
                )
                messages.success(request, "Password cambiata ✅")
                return redirect("account_profile")

            elif action == "delete_account":
                # Se NON hai l’endpoint, lascia commentato:
                # _api_request("DELETE", "profile/", token=token, timeout=15)
                messages.error(request, "Eliminazione account non abilitata su questo ambiente.")
                return redirect("account_profile")

            else:
                messages.error(request, "Azione non valida.")

        except requests.HTTPError as e:
            try:
                err = e.response.json()
                messages.error(request, err.get("detail") or str(e))
            except Exception:
                messages.error(request, f"Errore imprevisto: {e}")
        except Exception as e:
            messages.error(request, f"Errore imprevisto: {e}")
        return redirect("account_profile")

    # ---- GET (carica profilo)
    profilo = {}
    try:
        profilo = _api_request("GET", "profile/", token=token, timeout=10) or {}
    except Exception as e:
        messages.error(request, f"Impossibile caricare il profilo: {e}")

    # Flag visuali per “venditore verificato” (HOME richiede: telefono + almeno 1 social)
    phone_val = (profilo.get("phone_number") or "").strip()
    has_phone = bool(phone_val)

    socials = [
        (profilo.get("facebook_url") or "").strip(),
        (profilo.get("instagram_url") or "").strip(),
        (profilo.get("tiktok_url") or "").strip(),
        (profilo.get("x_url") or "").strip(),
    ]
    has_any_social = any(bool(s) for s in socials)
    is_verified_visual = has_phone and has_any_social

    ctx = {
        "profilo": profilo,
        "user_email": profilo.get("email") or "",
        "user_fullname": (profilo.get("first_name") or "") + (" " if profilo.get("last_name") else "") + (profilo.get("last_name") or ""),

        # variabili per il template (badge verifica)
        "has_phone": has_phone,
        "has_any_social": has_any_social,
        "is_verified_visual": is_verified_visual,

        # se il backend espone questi boolean, li puoi mostrare come badge read-only
        "phone_verified": bool(profilo.get("phone_verified")),
        "socials_verified": bool(profilo.get("socials_verified")),
    }
    return render(request, "web/account/profile.html", ctx)


# ============================================
# RECENSIONI (Placeholder)
# ============================================

def reviews_page(request):
    """Elenco recensioni."""
    return render(request, "web/reviews.html", {"reviews": []})


def reviews_create(request):
    """Crea recensione."""
    if request.method == "POST":
        messages.success(request, "Recensione inviata!")
        return redirect("reviews")
    return render(request, "web/reviews_create.html")


# ============================================
# ALTRE VIEW MANCANTI (se necessario)
# ============================================

# Aggiungi qui altre funzioni che potrebbero mancare...

def account_alerts_view(request):
    """
    Pagina 'I miei Alert' (notifiche gratuite + PRO).
    Mostra EventFollow (gratuiti) + Monitoraggi PRO.
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)

    # === ALERT GRATUITI (EventFollow) ===
    free_alerts = []
    try:
        data = _api_request("GET", "event-follows/", token=token, timeout=10) or {}
        rows = data.get("results", data if isinstance(data, list) else []) or []
        for ef in rows:
            ev = (ef.get("evento_info") or {})
            # Estrai la data dell'evento dalle performances
            performances = ev.get("performances", []) or []
            event_date = None
            if performances:
                # Prendi la prima performance
                first_perf = performances[0]
                starts_at = first_perf.get("starts_at_utc") or first_perf.get("data_inizio")
                if starts_at:
                    event_date = _fmt_iso_dmy_hm(starts_at)
            
            free_alerts.append({
                "id": ef.get("id"),
                "title": ev.get("nome_evento") or ev.get("nome") or "Evento",
                "event_date": event_date,
                "type": "free",
                "created_at": _fmt_iso_dmy_hm(ef.get("created_at") or ""),
                "expires_at": "Illimitato",  # Gli alert gratuiti non scadono
                "status": "Attivo",
            })
    except Exception:
        pass

    # === MONITORAGGI PRO ===
    pro_alerts = []
    try:
        data = _api_request("GET", "monitoraggi/my-pro/", token=token, timeout=10) or {}
        rows = data.get("results", data if isinstance(data, list) else []) or []
        for m in rows:
            ev = (m.get("evento_info") or {})
            perf = (m.get("performance_info") or {})
            
            # Estrai la data dell'evento
            event_date = None
            starts_at = perf.get("starts_at_utc") or perf.get("data_inizio")
            if starts_at:
                event_date = _fmt_iso_dmy_hm(starts_at)
            
            expires_iso = m.get("expires_at") or m.get("data_fine") or ""
            pro_alerts.append({
                "id": m.get("id"),
                "title": ev.get("nome_evento") or ev.get("nome") or "Evento",
                "event_date": event_date,
                "type": "pro",
                "created_at": _fmt_iso_dmy_hm(m.get("created_at") or ""),
                "expires_at": _fmt_iso_dmy_hm(expires_iso),
                "status": _map_sub_status(m),
            })
    except Exception:
        pass

    return render(request, "web/account/alerts.html", {
        "free_alerts": free_alerts,
        "pro_alerts": pro_alerts,
    })


@require_POST
def alert_pause_view(request, alert_id: int):
    """
    Mette in pausa un alert PRO (monitoraggio).
    """
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    
    try:
        _api_request("POST", f"monitoraggi/{alert_id}/pause/", token=token, timeout=10)
        messages.success(request, "Alert messo in pausa ✅")
    except Exception as e:
        messages.error(request, f"Impossibile mettere in pausa l'alert: {e}")
    
    return redirect(request.META.get("HTTP_REFERER") or reverse("account_alerts"))


@require_POST
def alert_resume_view(request, alert_id: int):
    """Riattiva un alert PRO in pausa."""
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    
    try:
        _api_request("POST", f"monitoraggi/{alert_id}/resume/", token=token, timeout=10)
        messages.success(request, "Alert riattivato ✅")
    except Exception as e:
        messages.error(request, f"Impossibile riattivare l'alert: {e}")
    
    return redirect(request.META.get("HTTP_REFERER") or reverse("account_alerts"))


@require_POST
def alert_delete_view(request, alert_id: int):
    """Elimina un alert PRO."""
    guard = _require_api_login(request, next_url=request.get_full_path())
    if guard:
        return guard

    token = request.session.get(SESSION_TOKEN_KEY)
    
    try:
        _api_request("DELETE", f"monitoraggi/{alert_id}/", token=token, timeout=10)
        messages.success(request, "Alert eliminato ✅")
    except Exception as e:
        messages.error(request, f"Impossibile eliminare l'alert: {e}")
    
    return redirect(reverse("account_alerts"))


@require_GET
def api_search_performances(request):
    """
    Proxy per ricerca performance: GET /api/search/performances/?q=...
    Chiama il backend API e ritorna JSON per l'autocomplete.
    """
    query = request.GET.get("q", "").strip()
    page_size = int(request.GET.get("page_size", 10))
    
    if not query or len(query) < 2:
        return JsonResponse({"results": []}, status=200)
    
    try:
        # Chiama l'API backend usando la funzione esistente
        data = _api_request(
            "GET",
            "performances/",
            params={
                "search": query,
                "page_size": page_size,
                "ordering": "starts_at_utc"
            }
        ) or {}
        
        results = data.get("results", [])
        
        # Normalizza i dati per il frontend
        normalized = []
        for item in results:
            normalized.append({
                "id": item.get("id"),
                "evento_nome": item.get("evento_nome", ""),
                "luogo_nome": item.get("luogo_nome", ""),
                "starts_at_utc": item.get("starts_at_utc", ""),
            })
        
        return JsonResponse({"results": normalized}, status=200)
        
    except Exception as e:
        return JsonResponse({"error": str(e), "results": []}, status=500)

