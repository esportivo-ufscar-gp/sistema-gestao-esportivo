"""
Rotas do módulo Estoque.

Pacote 4.3.3: o painel atende o GET da tela e o POST do formulário e dos botões + e −.
"""
from django.urls import path

from . import views

app_name = "estoque"

urlpatterns = [
    path("", views.painel, name="painel"),
]
