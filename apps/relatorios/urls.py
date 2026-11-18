"""Rotas do módulo Relatórios (pacote 4.7)."""
from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.painel, name="painel"),
]
