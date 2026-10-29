"""
Rotas do módulo Contas e acesso.

Pacote 4.1.1: entrada e saída. No Django 5 o logout só aceita POST, por isso o botão "Sair"
do base.html é um formulário.
"""
from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "contas"

urlpatterns = [
    path("entrar/", views.EntrarView.as_view(), name="entrar"),
    path("sair/", LogoutView.as_view(), name="sair"),
    path("painel/", views.painel, name="painel"),
]
