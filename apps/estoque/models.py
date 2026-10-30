"""
Modelos do módulo Estoque.

Pacote 4.3: entradas (4.3.1), baixa e sincronização entre canais (4.3.2), estoque mínimo e
alertas (4.3.3).

O MovimentoEstoque é o histórico do saldo: cada mudança de Produto.estoque_atual grava uma
linha aqui, na mesma transação. Quem escreve é sempre apps/estoque/services.py.
"""
from django.conf import settings
from django.db import models


class TipoDeMovimento(models.TextChoices):
    ENTRADA = "entrada", "Entrada"
    SAIDA_VENDA = "saida_venda", "Saída por venda"
    ESTORNO = "estorno", "Estorno"
    AJUSTE = "ajuste", "Ajuste (saída manual)"


# Movimentos que somam ao saldo; os demais subtraem.
TIPOS_DE_ENTRADA = (TipoDeMovimento.ENTRADA, TipoDeMovimento.ESTORNO)


class MovimentoEstoque(models.Model):
    """Uma mudança de saldo de um produto, com quem fez, quando e quanto."""

    produto = models.ForeignKey(
        "produtos.Produto",
        on_delete=models.PROTECT,  # produto com histórico não é excluído, só desativado
        related_name="movimentos",
        verbose_name="produto",
    )
    tipo = models.CharField("tipo", max_length=20, choices=TipoDeMovimento.choices)
    quantidade = models.IntegerField("quantidade")
    saldo_apos = models.IntegerField("saldo após")
    venda = models.ForeignKey(
        "vendas.Venda",
        on_delete=models.PROTECT,  # venda com movimento não é excluída, só cancelada
        null=True,
        blank=True,
        related_name="movimentos",
        verbose_name="venda",
        help_text="Preenchido na baixa por venda e no estorno de cancelamento.",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimentos_de_estoque",
        verbose_name="usuário",
        help_text="Fica em branco quando o movimento não parte de uma tela com usuário.",
    )
    motivo = models.CharField("motivo", max_length=200, blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "movimento de estoque"
        verbose_name_plural = "movimentos de estoque"
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["produto", "-criado_em"], name="movimento_produto_data"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantidade__gt=0),
                name="movimento_quantidade_maior_que_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(saldo_apos__gte=0),
                name="movimento_saldo_apos_nao_negativo",
            ),
            # O ajuste é uma saída manual e por isso exige motivo.
            models.CheckConstraint(
                condition=~models.Q(tipo=TipoDeMovimento.AJUSTE) | ~models.Q(motivo=""),
                name="movimento_ajuste_exige_motivo",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.quantidade} em {self.produto.codigo}"

    @property
    def soma_ao_saldo(self):
        """True quando o movimento aumentou o saldo do produto."""
        return self.tipo in TIPOS_DE_ENTRADA
