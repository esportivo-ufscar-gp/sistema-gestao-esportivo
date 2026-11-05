"""Filtros de template da loja online (pacote 4.5.1)."""
from django import template
from django.template.defaultfilters import floatformat

from ..services import disponibilidade as calcula_disponibilidade

register = template.Library()


@register.filter
def reais(valor):
    """Valor em reais no formato brasileiro: R$ 1.234,56."""
    # "2g" fixa duas casas e agrupa os milhares com o separador do idioma (pt-br: ponto).
    return f"R$ {floatformat(valor, '2g')}"


@register.filter
def disponibilidade(produto):
    """Em estoque, últimas unidades ou esgotado, calculado pelo serviço da loja."""
    return calcula_disponibilidade(produto)
