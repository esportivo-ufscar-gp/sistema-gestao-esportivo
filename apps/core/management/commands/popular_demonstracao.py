"""
Comando `python manage.py popular_demonstracao` (pacote 3.3, ambiente de demonstração).

Prepara um banco recém-migrado para a apresentação: perfis, um usuário de cada perfil,
catálogo de exemplo e um mês de vendas nos dois canais. Só roda em banco sem vendas e sem as
contas da demonstração.

A senha dos usuários vem de --senha ou da variável de ambiente DEMO_SENHA. Sem nenhuma das
duas, o comando gera uma senha aleatória e a mostra uma única vez, no fim da saída. Não existe
senha padrão: o repositório é público.
"""
import os
import secrets

from django.core.management.base import BaseCommand, CommandError

from apps.core.demonstracao import CLIENTES, EQUIPE, ErroDeDemonstracao, popular

VARIAVEL_DA_SENHA = "DEMO_SENHA"


class Command(BaseCommand):
    help = "Carrega usuários, catálogo e vendas de demonstração em um banco ainda sem vendas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--senha",
            help=(
                f"Senha dos usuários de demonstração. Prefira a variável {VARIAVEL_DA_SENHA}: o que vai "
                "na linha de comando fica no histórico do terminal. Sem nenhuma das duas, uma senha "
                "aleatória é gerada e mostrada uma única vez."
            ),
        )

    def handle(self, *args, **opcoes):
        senha, origem = self._senha(opcoes["senha"])

        try:
            resumo = popular(senha=senha)
        except ErroDeDemonstracao as erro:
            raise CommandError(str(erro))

        self.stdout.write(
            f"{resumo.vendas_pdv} vendas do PDV e {resumo.pedidos_online} pedidos online criados, "
            f"{resumo.canceladas} cancelados."
        )
        self.stdout.write("Acesse /contas/entrar/ com um destes e-mails:")
        for email, _, nome, perfil in EQUIPE:
            self.stdout.write(f"  {perfil:<14} {email}  ({nome})")
        nome, email, _ = CLIENTES[0]
        self.stdout.write(f"  {'cliente':<14} {email}  ({nome})")

        if origem is None:
            self.stdout.write(
                f"Senha gerada para todos esses usuários (anote; ela não será mostrada de novo): {senha}"
            )
        else:
            self.stdout.write(f"A senha de todos esses usuários é a informada em {origem}.")
        self.stdout.write(self.style.SUCCESS("Dados de demonstração carregados."))

    def _senha(self, informada):
        """A senha e de onde ela veio; origem None quando foi gerada agora."""
        if informada:
            return informada, "--senha"

        da_variavel = os.environ.get(VARIAVEL_DA_SENHA)
        if da_variavel:
            return da_variavel, VARIAVEL_DA_SENHA

        return secrets.token_urlsafe(16), None
