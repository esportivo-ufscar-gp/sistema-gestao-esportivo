"""
Formulários do módulo Loja online.

Pacote 4.5.3: checkout com identificação, retirada na loja e pagamento simulado.
"""
from django import forms

from .services import FORMAS_DE_PAGAMENTO_DA_LOJA


class FormularioDeCheckout(forms.Form):
    """
    Identificação e pagamento do checkout (HU12).

    Para o cliente logado, `identificado=True` tira os campos de identificação: o pedido usa o
    cadastro da conta. A entrega não é um campo: a única opção é a retirada na loja.
    """

    nome = forms.CharField(
        label="Nome completo",
        max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )
    telefone = forms.CharField(
        label="Telefone",
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "tel", "placeholder": "(16) 99999-9999"}
        ),
    )
    consentimento = forms.BooleanField(
        label="Autorizo o uso dos meus dados pessoais para processar este pedido e manter meu histórico de compras",
        error_messages={"required": "Para concluir o pedido, autorize o uso dos seus dados (LGPD)."},
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    forma_pagamento = forms.ChoiceField(
        label="Forma de pagamento",
        choices=FORMAS_DE_PAGAMENTO_DA_LOJA,
        error_messages={
            "required": "Escolha a forma de pagamento.",
            "invalid_choice": "Na loja online, o pagamento é por cartão de crédito ou PIX.",
        },
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )

    CAMPOS_DE_IDENTIFICACAO = ("nome", "email", "telefone", "consentimento")

    def __init__(self, *args, identificado=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.identificado = identificado

        if identificado:
            for campo in self.CAMPOS_DE_IDENTIFICACAO:
                del self.fields[campo]

    def dados_do_visitante(self):
        """Os dados de identificação no formato que apps/clientes/services.py recebe."""
        if self.identificado:
            return None

        return {
            "nome": self.cleaned_data["nome"],
            "email": self.cleaned_data["email"],
            "telefone": self.cleaned_data["telefone"],
            "consentiu": self.cleaned_data["consentimento"],
        }
