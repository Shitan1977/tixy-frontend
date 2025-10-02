from django.shortcuts import render

def home(request):
    return render(request, "web/home.html")

def faq(request):
    return render(request, "web/faq.html")

def vantaggi(request):
    return render(request, "web/vantaggi.html")


def funzioma(request):
    return render(request, "web/funziona.html")

def termini(request):
    return render(request, "web/termini.html")

def rivendita(request):
    return render(request, "web/rivendita.html")

def top(request):
    return render(request, "web/top.html")

def login(request):
    return render(request, "web/login.html")

def registrazione(request):
    return render(request, "web/registrazione.html")

def conferma_otp(request):
    return render(request, "web/conferma_otp.html")

def refresh_token(request):
    return render(request, "web/refresh_token.html")

def area_riservata_profilo(request):
    return render(request, "web/area_riservata/profilo.html")