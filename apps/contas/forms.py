"""
Formulários do módulo Contas e acesso.

Pacote 4.1.1: a tela de entrada usa e-mail e senha, e a mensagem de erro é sempre a mesma,
sem dizer qual dos dois campos está errado (HU01).
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm


class FormularioDeEntrada(AuthenticationForm):
    """AuthenticationForm com o campo de usuário apresentado como e-mail."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "E-mail ou senha inválidos.",
    }

    username = forms.CharField(
        label="E-mail",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autofocus": True,
            "autocomplete": "email",
            "inputmode": "email",
            "placeholder": "voce@exemplo.com",
        }),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "current-password",
        }),
    )
