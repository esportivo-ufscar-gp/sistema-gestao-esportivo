"""
Modelos do módulo Clientes.

Pacote 4.6: cadastro com consentimento LGPD (4.6.1) e histórico de compras (4.6.2).
"""
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.functions import Lower

Usuario = get_user_model()


class Cliente(models.Model):
    """Dados de quem compra na loja online (HU14)."""

    nome = models.CharField("nome completo", max_length=120)
    email = models.EmailField("e-mail", max_length=254)
    telefone = models.CharField("telefone", max_length=20)
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.PROTECT,
        related_name="cliente",
        verbose_name="usuário",
        null=True,
        blank=True,
    )
    consentimento_em = models.DateTimeField(
        "consentimento em",
        help_text="Data e hora do aceite dos termos e da política de privacidade (LGPD).",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="cliente_email_unico_ci",
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.email})"
