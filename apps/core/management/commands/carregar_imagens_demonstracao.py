"""
Comando `python manage.py carregar_imagens_demonstracao` (pacote 3.3, ambiente de demonstração).

Liga as fotos de apps/core/imagens_demonstracao aos produtos do catálogo de exemplo, pelo
código. O build do Render (build.sh) roda o comando a cada deploy, porque o disco do site é
recriado; em uso local, rode-o depois do popular_demonstracao para ver o catálogo com fotos.
"""
from django.core.management.base import BaseCommand

from apps.core.demonstracao import carregar_imagens


class Command(BaseCommand):
    help = "Liga as fotos do catálogo de exemplo aos produtos de mesmo código."

    def handle(self, *args, **opcoes):
        resultado = carregar_imagens()

        self.stdout.write(self.style.SUCCESS(f"Fotos ligadas aos produtos: {len(resultado.ligadas)}."))
        if resultado.mantidas:
            self.stdout.write(
                "Mantidas as fotos trocadas pelo Admin: " + ", ".join(resultado.mantidas) + "."
            )
        if resultado.sem_produto:
            self.stdout.write(
                "Fotos sem produto com o mesmo código: " + ", ".join(resultado.sem_produto) + "."
            )
