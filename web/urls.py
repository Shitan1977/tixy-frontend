import top
from django.urls import path
from .views import home, faq, vantaggi, funzioma, termini, rivendita, top, login, registrazione

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
]
