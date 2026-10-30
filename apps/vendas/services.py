"""
Regras de negócio do módulo Vendas (PDV).

Pacote 4.4: registro de venda (4.4.1) e cancelamento (4.4.2) na loja física.

A venda e a baixa de estoque são uma coisa só: tudo acontece dentro de uma transação, e quem
mexe no saldo é sempre apps/estoque/services.py (CLAUDE.md). Se faltar saldo em qualquer
item, a exceção sobe e a transação inteira volta atrás — nem a venda, nem os itens, nem o
número ficam gravados.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.estoque.services import baixar_itens, estornar_itens

from .models import (
    CanalDeVenda,
    ContadorDeVendas,
    FormaDePagamento,
    ItemVenda,
    StatusDeVenda,
    Venda,
)


class ErroDeVenda(Exception):
    """Erro de regra de negócio da venda."""


class VendaSemItens(ErroDeVenda):
    """Não dá para finalizar uma venda vazia."""


class FormaDePagamentoInvalida(ErroDeVenda):
    """A forma de pagamento é obrigatória e precisa ser uma das três aceitas."""


class VendaJaCancelada(ErroDeVenda):
    """Uma venda cancelada não é cancelada de novo."""


@transaction.atomic
def registrar_venda_pdv(vendedor, itens, forma_pagamento):
    """
    Finaliza uma venda do balcão (HU08).

    `itens` é uma sequência de pares (produto, quantidade), do mesmo formato que o serviço de
    estoque recebe. Devolve a Venda já concluída, com número, total e estoque baixado.
    """
    if not itens:
        raise VendaSemItens("Adicione pelo menos um item à venda.")

    if forma_pagamento not in FormaDePagamento.values:
        raise FormaDePagamentoInvalida("Escolha a forma de pagamento.")

    venda = Venda.objects.create(
        numero=_proximo_numero(),
        canal=CanalDeVenda.LOJA_FISICA,
        status=StatusDeVenda.CONCLUIDA,
        forma_pagamento=forma_pagamento,
        vendedor=vendedor,
        total=Decimal("0.00"),
    )

    # A baixa vem antes dos itens porque é ela que bloqueia os produtos e confere o saldo de
    # todos de uma vez. Os preços saem das linhas já bloqueadas, então o que é copiado para o
    # item é mesmo o preço do momento da finalização.
    movimentos = baixar_itens(itens, usuario=vendedor, venda=venda, motivo=f"Venda {venda}")
    precos = {movimento.produto.pk: movimento.produto.preco for movimento in movimentos}

    total = Decimal("0.00")
    for produto, quantidade in itens:
        preco = precos[produto.pk]
        ItemVenda.objects.create(
            venda=venda,
            produto=produto,
            quantidade=quantidade,
            preco_unitario=preco,
        )
        total += preco * quantidade

    venda.total = total
    venda.save(update_fields=["total"])

    return venda


@transaction.atomic
def cancelar_venda(venda, usuario):
    """
    Cancela uma venda concluída e devolve os itens ao estoque (HU09).

    Bloqueia a venda antes de olhar o status, para dois cliques simultâneos em "Cancelar"
    não estornarem o estoque duas vezes.
    """
    bloqueada = Venda.objects.select_for_update().get(pk=venda.pk)

    if bloqueada.cancelada:
        raise VendaJaCancelada(f"A venda {bloqueada} já está cancelada.")

    itens = [(item.produto, item.quantidade) for item in bloqueada.itens.select_related("produto")]
    estornar_itens(itens, usuario=usuario, venda=bloqueada, motivo=f"Cancelamento da venda {bloqueada}")

    bloqueada.status = StatusDeVenda.CANCELADA
    bloqueada.cancelada_em = timezone.now()
    bloqueada.cancelada_por = usuario
    bloqueada.save(update_fields=["status", "cancelada_em", "cancelada_por"])

    return bloqueada


def ultimas_vendas_do_pdv(limite=5):
    """As vendas mais recentes do balcão, para a lista do rodapé do PDV."""
    return Venda.objects.do_pdv().select_related("vendedor")[:limite]


def _proximo_numero():
    """
    Reserva o próximo número da sequência, bloqueando o contador.

    O bloqueio só é solto quando a transação da venda confirma; até lá, outra venda que peça
    um número fica esperando aqui em vez de repetir o mesmo.
    """
    ContadorDeVendas.objects.get_or_create(pk=1)
    contador = ContadorDeVendas.objects.select_for_update().get(pk=1)

    numero = contador.proximo_numero
    contador.proximo_numero = numero + 1
    contador.save(update_fields=["proximo_numero"])

    return numero
