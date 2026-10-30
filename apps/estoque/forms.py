"""
Formulários do módulo Estoque.

Pacote 4.3.1: o formulário "Movimentar estoque" do painel. A entrada aumenta o saldo; a
saída é um ajuste manual e, por isso, exige motivo.
"""
from django import forms

from .services import saldo_por_produto

ENTRADA = "entrada"
SAIDA = "saida"

TIPOS = [
    (ENTRADA, "Entrada de mercadoria"),
    (SAIDA, "Saída manual (ajuste)"),
]


class FormularioDeMovimento(forms.Form):
    produto = forms.ModelChoiceField(
        queryset=saldo_por_produto(),
        label="Produto",
        empty_label="Selecione o produto",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    tipo = forms.ChoiceField(
        choices=TIPOS,
        label="Movimento",
        initial=ENTRADA,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantidade = forms.IntegerField(
        label="Quantidade",
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "step": 1}),
    )
    motivo = forms.CharField(
        label="Motivo",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Obrigatório na saída: perda, quebra, conferência...",
        }),
    )

    def clean_motivo(self):
        return self.cleaned_data["motivo"].strip()

    def clean(self):
        dados = super().clean()

        if dados.get("tipo") == SAIDA and not dados.get("motivo"):
            self.add_error("motivo", "A saída manual exige um motivo.")

        return dados
