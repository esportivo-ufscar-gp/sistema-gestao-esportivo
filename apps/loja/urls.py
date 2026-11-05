"""
Rotas do módulo Loja online.

Pacote 4.5: catálogo (4.5.1), carrinho (4.5.2) e checkout com confirmação (4.5.3), abertos a
visitantes; adicionar ao carrinho só aceita POST. A gestão dos pedidos (4.5.4) fica no Admin.
"""
from django.urls import path

from . import views

app_name = "loja"

urlpatterns = [
    path("", views.catalogo, name="catalogo"),
    path("carrinho/", views.carrinho, name="carrinho"),
    path("carrinho/adicionar/", views.adicionar, name="adicionar"),
    path("checkout/", views.checkout, name="checkout"),
    path("pedidos/<int:numero>/confirmado/", views.pedido_confirmado, name="pedido_confirmado"),
]
