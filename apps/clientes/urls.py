"""
Rotas do módulo Clientes.

Pacote 4.6.1: cadastro de clientes. Pacote 4.6.2: histórico de compras ("Meus pedidos").
"""
from django.urls import path

from . import views

app_name = "clientes"

urlpatterns = [
    path("cadastro/", views.cadastro, name="cadastro"),
    path("meus-pedidos/", views.meus_pedidos, name="meus_pedidos"),
]
