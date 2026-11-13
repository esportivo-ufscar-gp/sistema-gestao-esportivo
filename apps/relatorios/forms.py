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


class SelectDeCategoria(forms.Select):
    """Lista as categorias inativas desabilitadas: elas aparecem, mas não podem ser escolhidas."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcao = super().create_option(name, value, label, selected, index, subindex, attrs)
        categoria = getattr(value, "instance", None)
        if categoria is not None and not categoria.ativa:
            opcao["attrs"]["disabled"] = True
        return opcao


class CampoDeCategoria(forms.ModelChoiceField):
    def label_from_instance(self, categoria):
        return categoria.nome if categoria.ativa else f"{categoria.nome} (inativa)"


class FiltroDeEstoque(forms.Form):
    """Categoria da posição de estoque (HU17); vazio mostra todas."""

    categoria = CampoDeCategoria(
        label="Categoria",
        required=False,
        # As ativas primeiro; as inativas vão para o fim da lista, marcadas e desabilitadas.
        queryset=Categoria.objects.order_by("-ativa", "nome"),
        empty_label="Todas",
        widget=SelectDeCategoria(attrs={"class": "form-select"}),
        error_messages={"invalid_choice": "Categoria não encontrada."},
    )
    incluir_inativos = forms.BooleanField(
        label="Incluir produtos inativos",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_categoria(self):
        categoria = self.cleaned_data.get("categoria")
        if categoria is not None and not categoria.ativa:
            raise forms.ValidationError(f"A categoria “{categoria.nome}” está inativa e não pode ser usada no filtro.")
        return categoria

    def filtros(self):
        """Categoria e inclusão de inativos já validados; um filtro inválido fica no padrão."""
        self.is_valid()
        dados = getattr(self, "cleaned_data", {})
        return dados.get("categoria"), dados.get("incluir_inativos", False)
