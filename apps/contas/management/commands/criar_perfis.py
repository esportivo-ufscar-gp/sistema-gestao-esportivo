"""
Comando `python manage.py criar_perfis` (pacote 4.1.2).

Cria os quatro perfis com as suas permissões. Pode rodar quantas vezes for preciso: é
idempotente. Rode de novo a cada pacote novo que acrescente permissões em
apps/contas/services.py.
"""
from django.core.management.base import BaseCommand

from apps.contas.services import criar_perfis


class Command(BaseCommand):
    help = "Cria ou atualiza os perfis (grupos) do sistema e as suas permissões."

    def handle(self, *args, **opcoes):
        resumo = criar_perfis()

        if opcoes["verbosity"]:
            for perfil, quantidade in resumo.items():
                self.stdout.write(f"{perfil}: {quantidade} permissão(ões)")
            self.stdout.write(self.style.SUCCESS("Perfis atualizados."))
