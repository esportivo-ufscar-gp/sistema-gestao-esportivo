"""
Formulários de filtro do módulo Relatórios.

Pacote 4.7: período e canal das vendas (4.7.1) e categoria da posição de estoque (4.7.2).
Os dois filtros usam GET: o endereço da tela guarda o filtro e pode ser compartilhado.
"""
from django import forms

from apps.produtos.models import Categoria
from apps.vendas.models import CanalDeVenda

from .services import periodo_padrao


class CampoDeData(forms.DateField):
    widget = forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")

    def __init__(self, **kwargs):
        super().__init__(input_formats=["%Y-%m-%d", "%d/%m/%Y"], **kwargs)


class FiltroDeVendas(forms.Form):
    """Data inicial, data final e canal do relatório de vendas (HU16)."""

    data_inicial = CampoDeData(label="Data inicial")
    data_final = CampoDeData(label="Data final")
    canal = forms.ChoiceField(
        label="Canal",
        required=False,
        choices=[("", "Todos")] + list(CanalDeVenda.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, dados=None, **kwargs):
        # Sem datas na URL, o relatório abre no mês corrente, já preenchido.
        dados = dados.copy() if dados is not None else {}
        inicio, fim = periodo_padrao()
        if not dados.get("data_inicial"):
            dados["data_inicial"] = inicio.isoformat()
        if not dados.get("data_final"):
            dados["data_final"] = fim.isoformat()
        super().__init__(dados, **kwargs)

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("data_inicial"), dados.get("data_final")
        if inicio and fim and inicio > fim:
            self.add_error("data_final", "A data final precisa ser igual ou posterior à data inicial.")
        return dados


class FiltroDeEstoque(forms.Form):
    """Categoria da posição de estoque (HU17); vazio mostra todas."""

    categoria = forms.ModelChoiceField(
        label="Categoria",
        required=False,
        queryset=Categoria.objects.order_by("nome"),
        empty_label="Todas",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
