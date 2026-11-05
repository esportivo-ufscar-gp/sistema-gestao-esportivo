"""
Rotas do módulo Loja online.

Pacote 4.5: catálogo (4.5.1) e carrinho (4.5.2). O catálogo e o carrinho são abertos a
visitantes; adicionar ao carrinho só aceita POST.
"""
from django.urls import path

from . import views

app_name = "loja"

urlpatterns = [
    path("", views.catalogo, name="catalogo"),
    path("carrinho/", views.carrinho, name="carrinho"),
    path("carrinho/adicionar/", views.adicionar, name="adicionar"),
]
