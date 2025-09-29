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