"""
Registro dos modelos do módulo Clientes no Django Admin.

Pacote 4.6: cadastro com consentimento LGPD (4.6.1) e histórico de compras (4.6.2).
"""
from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "telefone", "consentimento_em", "criado_em")
    search_fields = ("nome", "email")
    readonly_fields = ("consentimento_em", "criado_em")
    ordering = ("nome",)
