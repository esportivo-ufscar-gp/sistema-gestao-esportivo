"""
Modelos do módulo Loja online.

Pacote 4.5: catálogo (4.5.1), carrinho (4.5.2), checkout (4.5.3) e pedidos (4.5.4).

O pedido online é uma Venda com canal "online" (CLAUDE.md). O proxy PedidoOnline não cria
tabela: só dá ao Admin uma lista própria, que enxerga apenas esse canal, com permissões
separadas das vendas do PDV.
"""
from django.db import models

from apps.vendas.models import CanalDeVenda, Venda, VendaQuerySet


class PedidosOnlineManager(models.Manager.from_queryset(VendaQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(canal=CanalDeVenda.ONLINE)


class PedidoOnline(Venda):
    """Pedido da loja online, para a gestão das retiradas (HU13)."""

    objects = PedidosOnlineManager()

    class Meta:
        proxy = True
        verbose_name = "pedido online"
        verbose_name_plural = "pedidos online"
        ordering = ["-criado_em", "-id"]
