"""
Rotas do módulo Clientes.

Pacote 4.6.1: cadastro de clientes.
"""
from django.urls import path

from . import views

app_name = "clientes"

urlpatterns = [
    path("cadastro/", views.cadastro, name="cadastro"),
]
