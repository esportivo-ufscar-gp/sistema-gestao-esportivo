"""
Cria a linha única do contador de vendas (pacote 4.4.1).

A numeração começa em 1 e é compartilhada pelo PDV e pela loja online.
"""
from django.db import migrations


def cria_contador(apps, schema_editor):
    ContadorDeVendas = apps.get_model("vendas", "ContadorDeVendas")
    ContadorDeVendas.objects.get_or_create(pk=1, defaults={"proximo_numero": 1})


def remove_contador(apps, schema_editor):
    ContadorDeVendas = apps.get_model("vendas", "ContadorDeVendas")
    ContadorDeVendas.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("vendas", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(cria_contador, remove_contador),
    ]
