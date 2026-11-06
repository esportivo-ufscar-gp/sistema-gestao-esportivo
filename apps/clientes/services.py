"""
Regras de negócio do módulo Clientes.

Pacote 4.6: cadastro com consentimento LGPD (4.6.1) e histórico de compras (4.6.2).
Pacote 4.5.3: identificação do cliente no checkout da loja online.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from apps.vendas.models import Venda

from apps.contas.services import (
    PERFIL_ADMINISTRADOR,
    PERFIL_CLIENTE,
    PERFIL_ESTOQUISTA,
    PERFIL_VENDEDOR,
    perfil_do_usuario,
)
from .models import Cliente

Usuario = get_user_model()

PERFIS_DA_EQUIPE = (PERFIL_ADMINISTRADOR, PERFIL_VENDEDOR, PERFIL_ESTOQUISTA)


class ErroDeIdentificacao(Exception):
    """O checkout não conseguiu identificar o cliente; a mensagem diz o que fazer."""


class EquipeNaoCompraNaLoja(ErroDeIdentificacao):
    """Administrador, vendedor e estoquista não fazem pedidos pela loja online."""


class ContaSemCadastroDeCliente(ErroDeIdentificacao):
    """A conta logada não tem um Cliente ligado a ela."""


class ConsentimentoObrigatorio(ErroDeIdentificacao):
    """Sem o consentimento da LGPD, os dados do visitante não são gravados."""


class EmailDeUmaConta(ErroDeIdentificacao):
    """O e-mail informado pertence a uma conta: só quem entrar nela faz o pedido."""


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


# ------------------------------------------------------------------ Checkout da loja (4.5.3)
def e_da_equipe(usuario):
    """Administrador, vendedor e estoquista (ou qualquer conta com acesso ao Admin)."""
    return usuario.is_authenticated and (usuario.is_staff or perfil_do_usuario(usuario) in PERFIS_DA_EQUIPE)


def cliente_da_conta(usuario):
    """
    O cadastro de cliente de quem está logado (HU12): o checkout usa esses dados sem pedir de
    novo, e o consentimento é o que foi dado no cadastro.
    """
    if e_da_equipe(usuario):
        raise EquipeNaoCompraNaLoja(
            "Contas da equipe não fazem pedidos pela loja online. Para comprar, use uma conta de cliente."
        )

    try:
        return usuario.cliente
    except Cliente.DoesNotExist:
        raise ContaSemCadastroDeCliente(
            "Sua conta ainda não tem cadastro de cliente. Fale com a loja para completar o cadastro."
        )


@transaction.atomic
def identificar_visitante(nome, email, telefone, consentiu):
    """
    Identifica quem compra sem entrar numa conta (HU12).

    - E-mail novo: cria um Cliente sem conta de acesso, com o consentimento registrado agora.
    - E-mail de um cliente sem conta: reaproveita o cadastro e atualiza o consentimento.
    - E-mail que pertence a uma conta: recusa e pede o login, para ninguém fazer pedidos no nome
      de outra pessoa.

    O consentimento_em vem sempre do relógio do servidor, nunca do formulário.
    """
    if not consentiu:
        raise ConsentimentoObrigatorio("Para concluir o pedido, autorize o uso dos seus dados (LGPD).")

    email = email.strip().lower()

    if Usuario.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
        raise EmailDeUmaConta("Este e-mail pertence a uma conta. Entre na conta para concluir o pedido.")

    cliente = Cliente.objects.select_for_update().filter(email__iexact=email).first()

    if cliente is not None:
        if cliente.usuario_id is not None:
            raise EmailDeUmaConta("Este e-mail pertence a uma conta. Entre na conta para concluir o pedido.")

        cliente.consentimento_em = timezone.now()
        cliente.save(update_fields=["consentimento_em"])
        return cliente

    try:
        # Savepoint: se outro pedido criar o mesmo e-mail ao mesmo tempo, a restrição do banco
        # recusa este e a busca acima, repetida, encontra o cadastro que acabou de nascer.
        with transaction.atomic():
            return Cliente.objects.create(
                nome=nome.strip(),
                email=email,
                telefone=telefone.strip(),
                consentimento_em=timezone.now(),
            )
    except IntegrityError:
        return identificar_visitante(nome, email, telefone, consentiu)


def cliente_do_checkout(usuario, dados_do_visitante=None):
    """
    Quem é o cliente do pedido: o cadastro da conta logada ou o visitante identificado.

    `dados_do_visitante` traz nome, email, telefone e consentiu; só é lido para visitante.
    """
    if usuario.is_authenticated:
        return cliente_da_conta(usuario)

    if not dados_do_visitante:
        raise ErroDeIdentificacao("Informe nome, e-mail e telefone.")

    return identificar_visitante(**dados_do_visitante)


def pedidos_do_cliente(usuario, status=None):
    """
    Retorna a lista de pedidos do canal online do cliente associado ao usuário informado,
    ordenados do mais recente para o mais antigo, com os itens e produtos pré-carregados.
    Permite filtragem opcional por status ('aguardando_retirada', 'retirada', 'cancelada').
    """
    if not hasattr(usuario, 'cliente') or not usuario.cliente:
        return Venda.objects.none()

    qs = (
        Venda.objects.filter(cliente=usuario.cliente, canal='online')
        .prefetch_related('itens', 'itens__produto')
        .order_by('-criado_em')
    )

    if status in ['aguardando_retirada', 'retirada', 'cancelada']:
        qs = qs.filter(status=status)

    return qs
