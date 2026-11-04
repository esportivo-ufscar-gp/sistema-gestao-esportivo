"""
Regras de negócio do módulo Clientes.

Pacote 4.6: cadastro com consentimento LGPD (4.6.1) e histórico de compras (4.6.2).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.contas.services import PERFIL_CLIENTE
from .models import Cliente

Usuario = get_user_model()


def cadastrar_cliente(nome, email, telefone, senha):
    """
    Cadastra um novo cliente com consentimento LGPD (HU14).

    Cria a conta de acesso (User) e o perfil de Cliente dentro de uma transação atômica.
    O e-mail é único sem diferenciar maiúsculas e minúsculas.
    """
    email_limpo = email.strip().lower()

    if (
        Usuario.objects.filter(username__iexact=email_limpo).exists()
        or Usuario.objects.filter(email__iexact=email_limpo).exists()
        or Cliente.objects.filter(email__iexact=email_limpo).exists()
    ):
        raise ValidationError({"email": "Já existe uma conta cadastrada com este e-mail."})

    with transaction.atomic():
        usuario = Usuario.objects.create_user(
            username=email_limpo,
            email=email_limpo,
            password=senha,
            first_name=nome,
            is_staff=False,
        )

        grupo_cliente, _ = Group.objects.get_or_create(name=PERFIL_CLIENTE)
        usuario.groups.add(grupo_cliente)

        cliente = Cliente.objects.create(
            nome=nome,
            email=email_limpo,
            telefone=telefone,
            usuario=usuario,
            consentimento_em=timezone.now(),
        )

    return usuario, cliente
