"""
Modelos do módulo Vendas (PDV).

Pacote 4.4: registro de venda (4.4.1) e cancelamento (4.4.2) na loja física.

Venda do PDV e pedido online são a mesma entidade, separados pelo campo `canal` (CLAUDE.md).
O número é sequencial e compartilhado pelos dois canais: quem entrega o próximo número é o
ContadorDeVendas, uma linha única que o serviço bloqueia na hora de gravar a venda — é o que
garante número sem repetição mesmo com duas vendas simultâneas.
"""
from django.conf import settings
from django.db import models


class CanalDeVenda(models.TextChoices):
    LOJA_FISICA = "loja_fisica", "Loja física"
    ONLINE = "online", "Loja online"


class StatusDeVenda(models.TextChoices):
    CONCLUIDA = "concluida", "Concluída"
    AGUARDANDO_RETIRADA = "aguardando_retirada", "Aguardando retirada"
    RETIRADA = "retirada", "Retirada"
    CANCELADA = "cancelada", "Cancelada"


class FormaDePagamento(models.TextChoices):
    DINHEIRO = "dinheiro", "Dinheiro"
    CARTAO = "cartao", "Cartão"
    PIX = "pix", "PIX"


class VendaQuerySet(models.QuerySet):
    def validas(self):
        """Vendas que contam: tudo menos as canceladas. É a base dos relatórios (4.7)."""
        return self.exclude(status=StatusDeVenda.CANCELADA)

    def do_pdv(self):
        return self.filter(canal=CanalDeVenda.LOJA_FISICA)


class ContadorDeVendas(models.Model):
    """
    Guarda o próximo número de venda.

    Uma linha só, criada pela migração. O serviço a bloqueia com select_for_update() antes de
    ler e incrementar, então duas vendas simultâneas nunca recebem o mesmo número. Contar
    `max(numero) + 1` não serviria: duas transações leriam o mesmo máximo.
    """

    proximo_numero = models.PositiveIntegerField("próximo número", default=1)

    class Meta:
        verbose_name = "contador de vendas"
        verbose_name_plural = "contador de vendas"
        # Peça interna do serviço: ninguém administra o contador pelo Admin.
        default_permissions = ()

    def __str__(self):
        return f"Próximo número: {self.proximo_numero}"


class Venda(models.Model):
    """Uma venda do balcão (canal loja física) ou um pedido da loja online."""

    numero = models.PositiveIntegerField("número", unique=True)
    canal = models.CharField("canal", max_length=20, choices=CanalDeVenda.choices)
    status = models.CharField(
        "status",
        max_length=20,
        choices=StatusDeVenda.choices,
        default=StatusDeVenda.CONCLUIDA,
    )
    forma_pagamento = models.CharField("forma de pagamento", max_length=20, choices=FormaDePagamento.choices)
    total = models.DecimalField("total", max_digits=10, decimal_places=2, default=0)
    # O campo `cliente` entra no pacote 4.5.3, depois que o modelo Cliente (4.6.1) existir.
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendas",
        verbose_name="vendedor",
        help_text="Só nas vendas do PDV.",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    cancelada_em = models.DateTimeField("cancelada em", null=True, blank=True)
    cancelada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendas_canceladas",
        verbose_name="cancelada por",
    )

    objects = VendaQuerySet.as_manager()

    class Meta:
        verbose_name = "venda"
        verbose_name_plural = "vendas"
        ordering = ["-criado_em", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total__gte=0),
                name="venda_total_nao_negativo",
            ),
        ]

    def __str__(self):
        return self.numero_formatado

    @property
    def numero_formatado(self):
        """Número com quatro dígitos, como aparece na tela e no comprovante: #0043."""
        return f"#{self.numero:04d}"

    @property
    def cancelada(self):
        return self.status == StatusDeVenda.CANCELADA


class ItemVenda(models.Model):
    """Um produto dentro de uma venda, com o preço congelado no momento da venda."""

    venda = models.ForeignKey(
        Venda,
        on_delete=models.CASCADE,  # o item só existe dentro da venda
        related_name="itens",
        verbose_name="venda",
    )
    produto = models.ForeignKey(
        "produtos.Produto",
        on_delete=models.PROTECT,  # produto já vendido não é excluído, só desativado
        related_name="itens_vendidos",
        verbose_name="produto",
    )
    quantidade = models.IntegerField("quantidade")
    preco_unitario = models.DecimalField("preço unitário", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "item da venda"
        verbose_name_plural = "itens da venda"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantidade__gt=0),
                name="item_quantidade_maior_que_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(preco_unitario__gt=0),
                name="item_preco_unitario_maior_que_zero",
            ),
        ]

    def __str__(self):
        return f"{self.quantidade} x {self.produto.nome}"

    @property
    def subtotal(self):
        return self.quantidade * self.preco_unitario
