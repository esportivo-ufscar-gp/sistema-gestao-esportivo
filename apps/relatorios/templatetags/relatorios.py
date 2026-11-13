"""Filtros de template do módulo Relatórios (pacote 4.7)."""
from datetime import date

from django import template

from ..services import rotulo_da_situacao

register = template.Library()


@register.filter
def situacao(codigo):
    """Sem estoque, abaixo do mínimo ou normal."""
    return rotulo_da_situacao(codigo)


@register.filter
def ponto(valor):
    """Número com ponto decimal, para CSS e atributos ARIA (o pt-br usaria vírgula)."""
    return str(valor)


@register.filter
def data_iso(valor):
    """Data no formato do campo <input type="date"> (aaaa-mm-dd); outros valores passam iguais."""
    if isinstance(valor, date):
        return valor.isoformat()
    return valor
