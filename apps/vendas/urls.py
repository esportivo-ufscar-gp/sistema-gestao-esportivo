"""
Rotas do módulo Vendas (PDV).

Pacote 4.4: a tela do PDV atende o GET da busca e o POST de todas as ações do balcão
(acrescentar item, mudar quantidade, finalizar e cancelar).
"""
from django.urls import path

from . import views

app_name = "vendas"

urlpatterns = [
    path("pdv/", views.pdv, name="pdv"),
]
