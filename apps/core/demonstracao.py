"""
Dados de demonstração do sistema (pacote 3.3, ambiente de demonstração).

Monta um banco pronto para apresentar ao patrocinador: um usuário de cada perfil, o catálogo
de exemplo e um mês de vendas nos dois canais, com alguns cancelamentos e retiradas, para os
relatórios (4.7) e o painel de estoque terem o que mostrar.

Tudo passa pelos serviços do sistema: as vendas baixam estoque, os cancelamentos estornam e
as compras entram como movimento de entrada. Só as datas são ajustadas depois: as vendas se
espalham pelos últimos 30 dias, em horário comercial, e a compra inicial fica antes delas.
"""
import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.clientes.services import cadastrar_cliente
from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR, criar_perfis
from apps.estoque.models import MovimentoEstoque
from apps.estoque.services import registrar_entrada
from apps.produtos.models import Produto
from apps.vendas.models import FormaDePagamento, Venda
from apps.vendas.services import cancelar_venda, marcar_retirado, registrar_pedido_online, registrar_venda_pdv

SENHA_PADRAO = "demo-esportivo-2026"
DIAS_DE_HISTORICO = 30
COMPRA_INICIAL = 40  # unidades compradas de cada produto com saldo acima do mínimo

EQUIPE = (
    # e-mail, nome de usuário, nome, perfil, membro da equipe (Admin)
    ("admin@esportivo.demo", "carla", "Carla Mendes", PERFIL_ADMINISTRADOR, True),
    ("vendedor@esportivo.demo", "ana", "Ana Lima", PERFIL_VENDEDOR, False),
    ("estoquista@esportivo.demo", "bruno", "Bruno Costa", PERFIL_ESTOQUISTA, False),
)

CLIENTES = (
    ("Marina Souza", "marina@esportivo.demo", "(16) 99999-0001"),
    ("João Pereira", "joao@esportivo.demo", "(16) 99999-0002"),
    ("Luísa Ramos", "luisa@esportivo.demo", "(16) 99999-0003"),
)


class ErroDeDemonstracao(Exception):
    """Banco com vendas ou sem saldo para gerar a demonstração."""


@dataclass
class Resumo:
    usuarios: list = field(default_factory=list)
    vendas_pdv: int = 0
    pedidos_online: int = 0
    canceladas: int = 0


@transaction.atomic
def popular(senha=SENHA_PADRAO, vendas_pdv=40, pedidos_online=15, semente=2026):
    """
    Cria os dados de demonstração e devolve um Resumo.

    A `semente` deixa o resultado igual a cada execução, para a demonstração ser previsível.
    """
    if Venda.objects.exists():
        raise ErroDeDemonstracao("O banco já tem vendas. Use um banco novo para os dados de demonstração.")

    sorteio = random.Random(semente)
    resumo = Resumo()

    criar_perfis()
    if not Produto.objects.exists():
        call_command("loaddata", "dados_exemplo", verbosity=0)

    equipe = {dados[3]: _membro_da_equipe(senha, *dados, resumo=resumo) for dados in EQUIPE}
    clientes = [_cliente(senha, *dados, resumo=resumo) for dados in CLIENTES]
    estoquista, vendedor, admin = equipe[PERFIL_ESTOQUISTA], equipe[PERFIL_VENDEDOR], equipe[PERFIL_ADMINISTRADOR]

    # Produtos já abaixo do mínimo ficam como estão: é o que o relatório de estoque destaca.
    vendaveis = list(Produto.objects.filter(ativo=True, estoque_atual__gt=F("estoque_minimo")).order_by("id"))
    compras = [
        registrar_entrada(produto, COMPRA_INICIAL, usuario=estoquista, motivo="Compra inicial (demonstração)")
        for produto in vendaveis
    ]

    # Vendas do PDV e pedidos online intercalados, como num dia real de loja: assim os dois
    # canais ficam espalhados pelo mês inteiro, e não um canal inteiro antes do outro.
    canais = ["pdv"] * vendas_pdv + ["online"] * pedidos_online
    sorteio.shuffle(canais)
    pdv, online = [], []
    for canal in canais:
        if canal == "pdv":
            forma = sorteio.choice(FormaDePagamento.values)
            pdv.append(registrar_venda_pdv(vendedor, _itens(sorteio, vendaveis), forma))
        else:
            forma = sorteio.choice([FormaDePagamento.CARTAO, FormaDePagamento.PIX])
            online.append(registrar_pedido_online(sorteio.choice(clientes), _itens(sorteio, vendaveis), forma))
    resumo.vendas_pdv, resumo.pedidos_online = len(pdv), len(online)

    # Datas espalhadas pelos últimos 30 dias, na ordem dos números: a venda #0001 é a mais antiga.
    agora = timezone.now()
    vendas = sorted(pdv + online, key=lambda venda: venda.numero)
    datas = sorted(_momento_da_venda(sorteio, agora) for _ in vendas)
    for venda, quando in zip(vendas, datas):
        Venda.objects.filter(pk=venda.pk).update(criado_em=quando)
        MovimentoEstoque.objects.filter(venda=venda).update(criado_em=quando)

    # A compra inicial vem antes da primeira venda, para o histórico de estoque fazer sentido.
    inicio = timezone.make_aware(datetime.combine(_dia(agora, DIAS_DE_HISTORICO), time(8, 0)))
    MovimentoEstoque.objects.filter(pk__in=[compra.pk for compra in compras]).update(criado_em=inicio)

    # Metade dos pedidos online já foi retirada; os demais aguardam retirada na loja.
    for pedido in online[: len(online) // 2]:
        marcar_retirado(pedido, vendedor)

    # Algumas vendas canceladas, para mostrar que elas não entram nos relatórios.
    para_cancelar = pdv[3:4] + pdv[17:18] + online[-1:]
    for venda in para_cancelar:
        cancelar_venda(venda, admin)
    resumo.canceladas = len(para_cancelar)

    return resumo


def _membro_da_equipe(senha, email, nome_de_usuario, nome, perfil, staff, resumo):
    Usuario = get_user_model()
    usuario = Usuario.objects.filter(email__iexact=email).first()
    if usuario is None:
        usuario = Usuario.objects.create_user(
            username=nome_de_usuario, email=email, password=senha, first_name=nome, is_staff=staff,
        )
        resumo.usuarios.append(email)
    usuario.groups.add(Group.objects.get(name=perfil))
    return usuario


def _cliente(senha, nome, email, telefone, resumo):
    cliente = Cliente.objects.filter(email__iexact=email).first()
    if cliente is None:
        _, cliente = cadastrar_cliente(nome, email, telefone, senha)
        resumo.usuarios.append(email)
    return cliente


def _dia(agora, dias_atras):
    return timezone.localtime(agora).date() - timedelta(days=dias_atras)


def _momento_da_venda(sorteio, agora):
    """Um dia dos últimos 30, no horário da loja (9h às 19h); nunca depois de agora."""
    dia = _dia(agora, sorteio.randint(0, DIAS_DE_HISTORICO - 1))
    quando = timezone.make_aware(datetime.combine(dia, time(sorteio.randint(9, 18), sorteio.randint(0, 59))))
    if quando > agora:
        quando = agora - timedelta(minutes=sorteio.randint(1, 60))
    return quando


def _itens(sorteio, vendaveis):
    """De um a três produtos diferentes, uma ou duas unidades de cada, sem passar do saldo."""
    disponiveis = [p for p in vendaveis if _saldo(p) > p.estoque_minimo + 2]
    if not disponiveis:
        raise ErroDeDemonstracao("Não há saldo suficiente para gerar as vendas de demonstração.")
    escolhidos = sorteio.sample(disponiveis, k=min(len(disponiveis), sorteio.randint(1, 3)))
    return [(produto, sorteio.randint(1, 2)) for produto in escolhidos]


def _saldo(produto):
    produto.refresh_from_db(fields=["estoque_atual"])
    return produto.estoque_atual
