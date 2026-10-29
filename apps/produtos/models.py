"""
Modelos do módulo Produtos.

Pacote 4.2: categorias (4.2.1) e produtos (4.2.2).

As regras de negócio que valem para qualquer caminho de escrita (Admin, fixtures, serviços)
estão no próprio modelo: validadores para a validação em Python e restrições nomeadas para a
validação no banco de dados.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Categoria(models.Model):
    """Modalidade esportiva usada para organizar o catálogo (HU03)."""

    # unique=True cria a restrição UNIQUE no banco e também valida no Admin.
    nome = models.CharField("nome", max_length=60, unique=True)
    ativa = models.BooleanField(
        "ativa",
        default=True,
        help_text="Categorias inativas não aparecem no catálogo da loja online.",
    )

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Produto(models.Model):
    """Item do catálogo, vendido tanto no PDV quanto na loja online (HU04)."""

    codigo = models.CharField("código", max_length=20, unique=True)
    nome = models.CharField("nome", max_length=120)
    descricao = models.TextField("descrição", blank=True)
    imagem = models.ImageField("imagem", upload_to="produtos/", blank=True)
    preco = models.DecimalField(
        "preço",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,  # categoria com produtos vinculados não pode ser excluída
        related_name="produtos",
        verbose_name="categoria",
    )
    estoque_atual = models.IntegerField(
        "estoque atual",
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Somente o serviço de estoque (pacote 4.3) altera este saldo.",
    )
    estoque_minimo = models.IntegerField(
        "estoque mínimo",
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Quantidade que dispara o alerta de estoque baixo.",
    )
    ativo = models.BooleanField(
        "ativo",
        default=True,
        help_text="Produto já vendido não é excluído, apenas desativado.",
    )

    class Meta:
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        ordering = ["nome"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(preco__gt=0),
                name="produto_preco_maior_que_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(estoque_atual__gte=0),
                name="produto_estoque_atual_nao_negativo",
            ),
            models.CheckConstraint(
                condition=models.Q(estoque_minimo__gte=0),
                name="produto_estoque_minimo_nao_negativo",
            ),
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"
