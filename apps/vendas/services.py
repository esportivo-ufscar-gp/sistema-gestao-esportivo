"""
Regras de negócio do módulo Vendas (PDV).

Pacote 4.4: registro de venda (4.4.1) e cancelamento (4.4.2) na loja física.
Pacote 4.5: pedido da loja online (4.5.3), retirada e cancelamento do pedido (4.5.4).

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

# O balcão aceita as três formas; a loja online só as que dão para simular sem o cliente presente.
FORMAS_DE_PAGAMENTO_ONLINE = (FormaDePagamento.CARTAO, FormaDePagamento.PIX)


class ErroDeVenda(Exception):
    """Erro de regra de negócio da venda."""


class VendaSemItens(ErroDeVenda):
    """Não dá para finalizar uma venda vazia."""


class FormaDePagamentoInvalida(ErroDeVenda):
    """A forma de pagamento é obrigatória e precisa ser uma das aceitas no canal."""


class VendaJaCancelada(ErroDeVenda):
    """Uma venda cancelada não é cancelada de novo."""


class PedidoSemCliente(ErroDeVenda):
    """Pedido online sempre tem cliente."""


class StatusNaoPermite(ErroDeVenda):
    """O status atual não permite a mudança pedida (ex.: cancelar um pedido já retirado)."""


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

    return _baixa_e_grava_itens(venda, itens, usuario=vendedor, motivo=f"Venda {venda}")


@transaction.atomic
def registrar_pedido_online(cliente, itens, forma_pagamento):
    """
    Confirma um pedido da loja online (HU12).

    Usa a mesma numeração e a mesma baixa de estoque das vendas do PDV: o pedido nasce com canal
    online e status "aguardando retirada", com os preços do momento da confirmação. Aceita só
    cartão e PIX, simulados e aprovados na hora. Se faltar saldo em qualquer item, a exceção do
    estoque sobe e nada é gravado — nem o pedido, nem o número.
    """
    if cliente is None:
        raise PedidoSemCliente("Informe o cliente do pedido.")

    if not itens:
        raise VendaSemItens("O carrinho está vazio.")

    if forma_pagamento not in FORMAS_DE_PAGAMENTO_ONLINE:
        raise FormaDePagamentoInvalida("Na loja online, o pagamento é por cartão de crédito ou PIX.")

    venda = Venda.objects.create(
        numero=_proximo_numero(),
        canal=CanalDeVenda.ONLINE,
        status=StatusDeVenda.AGUARDANDO_RETIRADA,
        forma_pagamento=forma_pagamento,
        cliente=cliente,
        total=Decimal("0.00"),
    )

    return _baixa_e_grava_itens(venda, itens, usuario=cliente.usuario, motivo=f"Pedido online {venda}")


@transaction.atomic
def marcar_retirado(venda, usuario):
    """
    Registra que o cliente retirou o pedido na loja (HU13).

    Só vale para pedido online aguardando retirada. Bloqueia a venda antes de olhar o status,
    como o cancelamento, para retirada e cancelamento simultâneos não se cruzarem. O `usuario`
    é quem está no balcão; o modelo ainda não guarda quem entregou, só quando.
    """
    bloqueada = Venda.objects.select_for_update().get(pk=venda.pk)

    if not bloqueada.pedido_online:
        raise StatusNaoPermite(f"A venda {bloqueada} é do balcão e não tem retirada.")

    if bloqueada.status != StatusDeVenda.AGUARDANDO_RETIRADA:
        raise StatusNaoPermite(
            f"O pedido {bloqueada} está {bloqueada.get_status_display().lower()}; só um pedido "
            f"aguardando retirada pode ser marcado como retirado."
        )

    bloqueada.status = StatusDeVenda.RETIRADA
    bloqueada.retirada_em = timezone.now()
    bloqueada.save(update_fields=["status", "retirada_em"])

    return bloqueada


@transaction.atomic
def cancelar_venda(venda, usuario):
    """
    Cancela uma venda e devolve os itens ao estoque (HU09 e HU13).

    Vale para a venda concluída do PDV e para o pedido online que ainda aguarda retirada; um
    pedido já retirado não é cancelado. Bloqueia a venda antes de olhar o status, para dois
    cliques simultâneos em "Cancelar" não estornarem o estoque duas vezes.
    """
    bloqueada = Venda.objects.select_for_update().get(pk=venda.pk)
    nome = f"O pedido {bloqueada}" if bloqueada.pedido_online else f"A venda {bloqueada}"
    sufixo = "o" if bloqueada.pedido_online else "a"

    if bloqueada.cancelada:
        raise VendaJaCancelada(f"{nome} já está cancelad{sufixo}.")

    if bloqueada.status == StatusDeVenda.RETIRADA:
        raise StatusNaoPermite(f"{nome} já foi retirado e não pode ser cancelado.")

    itens = [(item.produto, item.quantidade) for item in bloqueada.itens.select_related("produto")]
    estornar_itens(itens, usuario=usuario, venda=bloqueada, motivo=f"Cancelamento d{sufixo} {nome[2:]}")

    bloqueada.status = StatusDeVenda.CANCELADA
    bloqueada.cancelada_em = timezone.now()
    bloqueada.cancelada_por = usuario
    bloqueada.save(update_fields=["status", "cancelada_em", "cancelada_por"])

    return bloqueada


def ultimas_vendas_do_pdv(limite=5):
    """As vendas mais recentes do balcão, para a lista do rodapé do PDV."""
    return Venda.objects.do_pdv().select_related("vendedor")[:limite]


def _baixa_e_grava_itens(venda, itens, usuario, motivo):
    """
    Baixa o estoque, grava os itens com o preço do momento e fecha o total da venda.

    A baixa vem antes dos itens porque é ela que bloqueia os produtos e confere o saldo de
    todos de uma vez. Os preços saem das linhas já bloqueadas, então o que é copiado para o
    item é mesmo o preço do momento da finalização.
    """
    movimentos = baixar_itens(itens, usuario=usuario, venda=venda, motivo=motivo)
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
