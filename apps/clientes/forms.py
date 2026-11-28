from django import forms
from django.utils.safestring import mark_safe

from .models import Cliente
from .services import EMAIL_EM_USO, email_em_uso


class FormularioDeCadastroCliente(forms.ModelForm):
    """Formulário de cadastro de clientes com consentimento LGPD."""

    nome = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Seu nome completo"}
        ),
    )
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "voce@exemplo.com"}
        ),
    )
    telefone = forms.CharField(
        label="Telefone",
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "(16) 99999-9999"}
        ),
    )
    senha = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Mínimo de 8 caracteres"}
        ),
    )
    confirmacao_senha = forms.CharField(
        label="Confirmação da senha",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Repita a senha"}
        ),
    )

    aceito_termos = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input mt-1"}),
        label=mark_safe(
            'Li e aceito os '
            '<a href="/termos/" target="_blank" class="text-primary text-decoration-underline">Termos de uso</a> '
            'e a '
            '<a href="/privacidade/" target="_blank" class="text-primary text-decoration-underline">'
            'Política de Privacidade</a>.'
        ),
    )

    autorizo_lgpd = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input mt-1"}),
        label=mark_safe(
            'Autorizo o uso dos meus dados pessoais para as finalidades acima, conforme a '
            '<a href="https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm" '
            'target="_blank" rel="noopener noreferrer" class="text-primary text-decoration-underline">'
            'Lei Geral de Proteção de Dados (LGPD)</a>.'
        ),
    )

    class Meta:
        model = Cliente
        fields = ["nome", "email", "telefone"]

    def clean_email(self):
        # Conferido aqui, e não só no serviço: sem isso, o e-mail de um cliente já cadastrado
        # caía na restrição do banco, e a tela mostrava a mensagem técnica dela
        # ('Restrição "cliente_email_unico_ci" foi violada.') no topo do formulário.
        email = self.cleaned_data["email"]
        if email_em_uso(email):
            raise forms.ValidationError(EMAIL_EM_USO)
        return email

    def clean(self):
        cleaned_data = super().clean()
        senha = cleaned_data.get("senha")
        confirmacao_senha = cleaned_data.get("confirmacao_senha")

        if senha and confirmacao_senha and senha != confirmacao_senha:
            self.add_error("confirmacao_senha", "As senhas não coincidem.")

        return cleaned_data
