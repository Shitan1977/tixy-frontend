# web/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Statiche / contenuti
    path("", views.home, name="home"),
    path("top/", views.top, name="top"),
    path("faq/", views.faq, name="faq"),
    path("vantaggi/", views.vantaggi, name="vantaggi"),
    path("funziona/", views.funzioma, name="funziona"),  # la view si chiama "funzioma"
    path("termini/", views.termini, name="termini"),
    path("rivendita/", views.rivendita, name="rivendita"),
    path("privacy/", views.privacy, name="privacy"),
    path("contatti/", views.contatti, name="contatti"),  # <-- AGGIUNGI QUESTA RIGA

    # Auth / account
    path("login/", views.login, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("registrazione/", views.registrazione, name="registrazione"),
    path("verifica-otp/", views.verifica_otp, name="verifica-otp"),
    path("password/forgot/", views.password_forgot_view, name="password_forgot"),
    path("password/reset/confirm/", views.password_reset_confirm_view, name="password_reset_confirm"),
    path("account/", views.account_admin, name="account_admin"),

    # Search & catalogo
    path("search", views.search, name="search"),  # (voluto) senza slash finale
    path("evento/<int:perf_id>/", views.event_listings, name="event-listings"),

    # Checkout flow
    path("acquista/<int:listing_id>/", views.checkout_view, name="acquista"),
    path("pagamento/<int:order_id>/", views.payment_view, name="pagamento"),
    path("conferma/<int:order_id>/", views.order_confirmed_view, name="ordine_confermato"),
    path("ordine/<int:order_id>/", views.order_summary_view, name="ordine"),

    # Alert / PRO
    path("evento/<int:event_id>/alert/", views.attiva_alert, name="attiva_alert"),
    path("abbonati/", views.attiva_pro, name="attiva_pro"),
    path("abbonati/carrello/", views.pro_cart, name="pro_cart"),
    path("abbonati/pagamento/", views.pro_pagamento, name="pro_pagamento"),
    path("abbonati/confermato/", views.pro_done, name="pro_done"),

    # Eventi (indice e date)
    path("eventi/", views.events_index, name="events_index"),
    path("evento/<int:event_id>/date/", views.event_dates, name="event_dates"),

    # Recensioni
    path("recensioni/", views.reviews_page, name="reviews"),
    path("recensioni/crea/", views.reviews_create, name="reviews_create"),

    # Account: Alert
    path("account/alerts/", views.account_alerts_view, name="account_alerts"),
    path("account/alerts/<int:alert_id>/pause/", views.alert_pause_view, name="alert_pause"),
    path("account/alerts/<int:alert_id>/resume/", views.alert_resume_view, name="alert_resume"),
    path("account/alerts/<int:alert_id>/delete/", views.alert_delete_view, name="alert_delete"),

    # Account: Biglietti (acquisti)
    path("account/tickets/", views.account_tickets_view, name="account_tickets"),
    path("account/tickets/<int:order_id>/download/", views.ticket_download_proxy, name="ticket_download_proxy"),

    # Account: Rivendita
    path("account/resales/", views.account_resales_view, name="account_resales"),
    path("account/resales/upload/", views.resales_upload, name="resales_upload"),
    path("account/resales/upload/<int:upload_id>/review/", views.resales_upload_review_view, name="resales_upload_review"),

# Account: Supporto (ticket)
    path("account/support/", views.account_support_list, name="account_support_list"),
    path("account/support/nuovo/", views.account_support_new, name="account_support_new"),
    path("account/support/<int:ticket_id>/", views.account_support_detail, name="account_support_detail"),
    path("account/profilo/", views.account_profile_view, name="account_profile"),

    # Account: Abbonamenti (read-only)
    path("account/abbonamenti/", views.account_subscriptions_view, name="account_subscriptions"),

    path("evento/perf/<int:perf_id>/date/", views.event_dates_from_perf, name="event_dates_from_perf"),
    path("evento/<int:event_id>/date/", views.event_dates, name="event_dates"),
    path("evento/<int:perf_id>/", views.event_listings, name="event_listings"),

    # API proxy per autocomplete
    path('api/search/performances/', views.api_search_performances, name='api-search-performances'),

]
