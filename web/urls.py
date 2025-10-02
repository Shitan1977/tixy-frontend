import top
from django.urls import path
from .views import home, faq, vantaggi, funzioma, termini, rivendita, top, login, registrazione, conferma_otp, refresh_token, area_riservata_profilo

urlpatterns = [
    path("", home, name="home"),
    path("faq/", faq, name="faq"),
    path("vantaggi/", vantaggi, name="vantaggi"),
    path("funziona/", funzioma, name="funziona"),
    path("termini/", termini, name="termini"),
    path("rivendita/", rivendita, name="rivendita"),
    path("top/", top, name="top"),
    path("login/", login, name="login"),
    path("registrazione/", registrazione, name="registrazione"),
    path("conferma_otp/", conferma_otp, name="conferma_otp"),
    path("refresh_token/", refresh_token, name="refresh_token"),
    path("area_riservata/profilo/", area_riservata_profilo, name="area_riservata_profilo"),
]
