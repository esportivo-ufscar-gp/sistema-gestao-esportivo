"""
Comando `python manage.py popular_demonstracao` (pacote 3.3, ambiente de demonstração).

Prepara um banco recém-migrado para a apresentação: perfis, um usuário de cada perfil,
catálogo de exemplo e um mês de vendas nos dois canais. Só roda em banco sem vendas.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core.demonstracao import EQUIPE, SENHA_PADRAO, ErroDeDemonstracao, popular


class Command(BaseCommand):
    help = "Carrega usuários, catálogo e vendas de demonstração em um banco ainda sem vendas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--senha",
            default=SENHA_PADRAO,
            help="Senha dos usuários de demonstração. Troque-a em um ambiente publicado na internet.",
        )

    def handle(self, *args, **opcoes):
        try:
            resumo = popular(senha=opcoes["senha"])
        except ErroDeDemonstracao as erro:
            raise CommandError(str(erro))

        self.stdout.write(
            f"{resumo.vendas_pdv} vendas do PDV e {resumo.pedidos_online} pedidos online criados, "
            f"{resumo.canceladas} cancelados."
        )
        self.stdout.write("Acesse /contas/entrar/ com um destes e-mails:")
        for email, _, nome, perfil, _ in EQUIPE:
            self.stdout.write(f"  {perfil:<14} {email}  ({nome})")
        self.stdout.write("  cliente        marina@esportivo.demo  (Marina Souza)")
        self.stdout.write(self.style.SUCCESS("Dados de demonstração carregados."))
