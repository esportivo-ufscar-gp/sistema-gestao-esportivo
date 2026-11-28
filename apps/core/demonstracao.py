"""
Dados de demonstração do sistema (pacote 3.3, ambiente de demonstração).

Monta um banco pronto para apresentar ao patrocinador: um usuário de cada perfil, o catálogo
de exemplo e um mês de vendas nos dois canais, com alguns cancelamentos e retiradas, para os
relatórios (4.7) e o painel de estoque terem o que mostrar.

Tudo passa pelos serviços do sistema: o saldo inicial do catálogo e as compras entram como
movimento de entrada, as vendas baixam estoque e os cancelamentos estornam. Assim, para cada
produto, a soma dos movimentos é igual ao saldo. Só as datas são ajustadas depois: as vendas
se espalham pelos últimos 30 dias, em horário comercial, e o saldo inicial e a compra ficam
antes delas.

Não existe senha padrão: quem chama informa a senha (o comando popular_demonstracao a recebe
de --senha ou de DEMO_SENHA, ou gera uma aleatória). O repositório é público, e uma senha
escrita aqui abriria o Admin do ambiente hospedado para qualquer pessoa.
"""
import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.color import no_style
from django.db import connection, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.clientes.services import cadastrar_cliente
from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR, criar_perfis
from apps.estoque.models import TIPOS_DE_ENTRADA, MovimentoEstoque
from apps.estoque.services import registrar_entrada
from apps.produtos.models import Categoria, Produto
from apps.vendas.models import FormaDePagamento, Venda
from apps.vendas.services import cancelar_venda, marcar_retirado, registrar_pedido_online, registrar_venda_pdv

DIAS_DE_HISTORICO = 30
COMPRA_INICIAL = 40  # unidades compradas de cada produto com saldo acima do mínimo
FIXTURE_DO_CATALOGO = "dados_exemplo.json"
MOTIVO_SALDO_INICIAL = "Saldo inicial"

EQUIPE = (
    # e-mail, nome de usuário, nome, perfil. Todos entram no Admin (is_staff), e cada um vê lá
    # só o que as permissões do seu perfil liberam: o vendedor consulta vendas, o estoquista
    # consulta e registra movimentos.
    ("admin@esportivo.demo", "carla", "Carla Mendes", PERFIL_ADMINISTRADOR),
    ("vendedor@esportivo.demo", "ana", "Ana Lima", PERFIL_VENDEDOR),
    ("estoquista@esportivo.demo", "bruno", "Bruno Costa", PERFIL_ESTOQUISTA),
)

CLIENTES = (
    ("Marina Souza", "marina@esportivo.demo", "(16) 99999-0001"),
    ("João Pereira", "joao@esportivo.demo", "(16) 99999-0002"),
    ("Luísa Ramos", "luisa@esportivo.demo", "(16) 99999-0003"),
)


class ErroDeDemonstracao(Exception):
    """O banco não está pronto para a demonstração, ou a senha não serve."""


@dataclass
class Resumo:
    usuarios: list = field(default_factory=list)
    vendas_pdv: int = 0
    pedidos_online: int = 0
    canceladas: int = 0


def emails_da_demonstracao():
    """E-mails das contas que a demonstração cria: a equipe e os clientes."""
    return [dados[0] for dados in EQUIPE] + [dados[1] for dados in CLIENTES]


def saldo_pelos_movimentos(produto):
    """Entradas e estornos somam; saídas por venda e ajustes subtraem."""
    totais = produto.movimentos.aggregate(
        entradas=Sum("quantidade", filter=Q(tipo__in=TIPOS_DE_ENTRADA), default=0),
        saidas=Sum("quantidade", filter=~Q(tipo__in=TIPOS_DE_ENTRADA), default=0),
    )
    return totais["entradas"] - totais["saidas"]


@transaction.atomic
def popular(senha, vendas_pdv=40, pedidos_online=15, semente=2026):
    """
    Cria os dados de demonstração e devolve um Resumo.

    Recusa, sem gravar nada, um banco que já tem vendas, contas com os e-mails da demonstração
    ou produtos com saldo sem histórico, e também uma senha que não passe nos validadores do
    Django. A `semente` deixa o resultado igual a cada execução, para a demonstração ser
    previsível.
    """
    if Venda.objects.exists():
        raise ErroDeDemonstracao("O banco já tem vendas. Use um banco novo para os dados de demonstração.")

    existentes = _contas_ja_existentes()
    if existentes:
        raise ErroDeDemonstracao(
            "Já existem contas com os dados da demonstração: " + ", ".join(existentes) + ". "
            "O comando não reaproveita contas existentes; use um banco novo."
        )

    try:
        password_validation.validate_password(senha)
    except ValidationError as erro:
        raise ErroDeDemonstracao("Senha fraca para os usuários de demonstração: " + " ".join(erro.messages))

    sorteio = random.Random(semente)
    resumo = Resumo()

    criar_perfis()
    equipe = {dados[3]: _membro_da_equipe(senha, *dados, resumo=resumo) for dados in EQUIPE}
    clientes = [_cliente(senha, *dados, resumo=resumo) for dados in CLIENTES]
    estoquista, vendedor, admin = equipe[PERFIL_ESTOQUISTA], equipe[PERFIL_VENDEDOR], equipe[PERFIL_ADMINISTRADOR]

    saldos_iniciais = _prepara_catalogo(estoquista)

    # Produtos já abaixo do mínimo ficam como estão: é o que o relatório de estoque destaca.
    vendaveis = list(Produto.objects.filter(ativo=True, estoque_atual__gt=F("estoque_minimo")).order_by("id"))
    compras = [
        registrar_entrada(produto, COMPRA_INICIAL, usuario=estoquista, motivo="Compra inicial (demonstração)")
        for produto in vendaveis
    ]

    # Vendas do PDV e pedidos online intercalados, como num dia real de loja: assim os dois
    # canais ficam espalhados pelo mês inteiro, e não um canal inteiro antes do outro.
    canais = ["pdv"] * vendas_pdv + ["online"] * pedidos_online
    sorteio.shuffle(canais)
    pdv, online = [], []
    for canal in canais:
        if canal == "pdv":
            forma = sorteio.choice(FormaDePagamento.values)
            pdv.append(registrar_venda_pdv(vendedor, _itens(sorteio, vendaveis), forma))
        else:
            forma = sorteio.choice([FormaDePagamento.CARTAO, FormaDePagamento.PIX])
            online.append(registrar_pedido_online(sorteio.choice(clientes), _itens(sorteio, vendaveis), forma))
    resumo.vendas_pdv, resumo.pedidos_online = len(pdv), len(online)

    # Datas espalhadas pelos últimos 30 dias, na ordem dos números: a venda #0001 é a mais antiga.
    agora = timezone.now()
    vendas = sorted(pdv + online, key=lambda venda: venda.numero)
    datas = sorted(_momento_da_venda(sorteio, agora) for _ in vendas)
    for venda, quando in zip(vendas, datas):
        Venda.objects.filter(pk=venda.pk).update(criado_em=quando)
        MovimentoEstoque.objects.filter(venda=venda).update(criado_em=quando)

    # O saldo inicial vem um dia antes da compra, e a compra antes da primeira venda, para o
    # histórico de estoque ficar em ordem cronológica.
    compra_em = timezone.make_aware(datetime.combine(_dia(agora, DIAS_DE_HISTORICO), time(8, 0)))
    MovimentoEstoque.objects.filter(pk__in=[compra.pk for compra in compras]).update(criado_em=compra_em)
    MovimentoEstoque.objects.filter(pk__in=[entrada.pk for entrada in saldos_iniciais]).update(
        criado_em=compra_em - timedelta(days=1)
    )

    # Metade dos pedidos online já foi retirada; os demais aguardam retirada na loja.
    for pedido in online[: len(online) // 2]:
        marcar_retirado(pedido, vendedor)

    # Algumas vendas canceladas, para mostrar que elas não entram nos relatórios.
    para_cancelar = pdv[3:4] + pdv[17:18] + online[-1:]
    for venda in para_cancelar:
        cancelar_venda(venda, admin)
    resumo.canceladas = len(para_cancelar)

    return resumo


def _contas_ja_existentes():
    """E-mails e nomes de usuário da demonstração que já estão em uso, em ordem alfabética."""
    Usuario = get_user_model()
    procurados = emails_da_demonstracao() + [dados[1] for dados in EQUIPE]

    em_uso = set()
    for valor in procurados:
        if (
            Usuario.objects.filter(Q(email__iexact=valor) | Q(username__iexact=valor)).exists()
            or Cliente.objects.filter(email__iexact=valor).exists()
        ):
            em_uso.add(valor)
    return sorted(em_uso)


def _membro_da_equipe(senha, email, nome_de_usuario, nome, perfil, resumo):
    usuario = get_user_model().objects.create_user(
        username=nome_de_usuario, email=email, password=senha, first_name=nome, is_staff=True,
    )
    usuario.groups.add(Group.objects.get(name=perfil))
    resumo.usuarios.append(email)
    return usuario


def _cliente(senha, nome, email, telefone, resumo):
    _, cliente = cadastrar_cliente(nome, email, telefone, senha)
    resumo.usuarios.append(email)
    return cliente


def _prepara_catalogo(estoquista):
    """
    Garante um catálogo cujo saldo é explicado pelos movimentos e devolve as entradas de saldo
    inicial que criou.

    Banco sem produtos: carrega o catálogo de exemplo com saldo zero e dá entrada no saldo de
    cada produto pelo serviço de estoque, com o motivo "Saldo inicial". Banco com produtos: só
    segue se o saldo de cada um bater com o histórico, para a demonstração não herdar um saldo
    que nenhum movimento explica.
    """
    if Produto.objects.exists():
        sem_historico = [
            produto.nome for produto in Produto.objects.order_by("nome")
            if produto.estoque_atual != saldo_pelos_movimentos(produto)
        ]
        if sem_historico:
            raise ErroDeDemonstracao(
                "Estes produtos têm saldo sem movimento de estoque que o explique: "
                + ", ".join(sem_historico) + ". Use um banco novo para os dados de demonstração."
            )
        return []

    saldos = _carrega_catalogo_sem_saldo()
    return [
        registrar_entrada(produto, saldos[produto.pk], usuario=estoquista, motivo=MOTIVO_SALDO_INICIAL)
        for produto in Produto.objects.filter(pk__in=saldos).order_by("id")
        if saldos[produto.pk] > 0
    ]


def _carrega_catalogo_sem_saldo():
    """
    Grava as categorias e os produtos da fixture com saldo zero e devolve {id: saldo da fixture}.

    O saldo nunca é gravado direto no produto (CLAUDE.md): ele entra em seguida pelo serviço de
    estoque. Por isso a fixture é lida aqui, e não com loaddata, que gravaria o saldo pronto.
    """
    caminho = Path(apps.get_app_config("produtos").path) / "fixtures" / FIXTURE_DO_CATALOGO
    saldos = {}

    with caminho.open(encoding="utf-8") as arquivo:
        for registro in serializers.deserialize("json", arquivo):
            objeto = registro.object
            if isinstance(objeto, Produto):
                saldos[objeto.pk] = objeto.estoque_atual
                objeto.estoque_atual = 0
            registro.save()

    # A fixture traz os ids prontos; como no loaddata, o contador de ids do banco é ajustado
    # para os próximos cadastros não repetirem um id já usado.
    with connection.cursor() as cursor:
        for comando in connection.ops.sequence_reset_sql(no_style(), [Categoria, Produto]):
            cursor.execute(comando)

    return saldos


def _dia(agora, dias_atras):
    return timezone.localtime(agora).date() - timedelta(days=dias_atras)


def _momento_da_venda(sorteio, agora):
    """Um dia dos últimos 30, no horário da loja (9h às 19h); nunca depois de agora."""
    dia = _dia(agora, sorteio.randint(0, DIAS_DE_HISTORICO - 1))
    quando = timezone.make_aware(datetime.combine(dia, time(sorteio.randint(9, 18), sorteio.randint(0, 59))))
    if quando > agora:
        quando = agora - timedelta(minutes=sorteio.randint(1, 60))
    return quando


def _itens(sorteio, vendaveis):
    """De um a três produtos diferentes, uma ou duas unidades de cada, sem passar do saldo."""
    disponiveis = [p for p in vendaveis if _saldo(p) > p.estoque_minimo + 2]
    if not disponiveis:
        raise ErroDeDemonstracao("Não há saldo suficiente para gerar as vendas de demonstração.")
    escolhidos = sorteio.sample(disponiveis, k=min(len(disponiveis), sorteio.randint(1, 3)))
    return [(produto, sorteio.randint(1, 2)) for produto in escolhidos]


def _saldo(produto):
    produto.refresh_from_db(fields=["estoque_atual"])
    return produto.estoque_atual


# ------------------------------------------------------------------ Fotos do catálogo
# As fotos do catálogo de exemplo ficam versionadas nesta pasta, uma por produto, com o código
# no nome (100110.jpg). A pasta media/ não vai para o repositório (CLAUDE.md), e no Render o
# disco do site é recriado a cada deploy e a cada vez que ele acorda: por isso o build roda
# carregar_imagens a cada deploy, gravando de novo os arquivos na media/.
PASTA_DAS_IMAGENS = Path(__file__).resolve().parent / "imagens_demonstracao"


@dataclass
class ResultadoDasImagens:
    ligadas: list = field(default_factory=list)       # códigos que receberam a foto da pasta
    mantidas: list = field(default_factory=list)      # já tinham outra foto, que ainda existe
    sem_produto: list = field(default_factory=list)   # fotos cujo código não está no catálogo


def carregar_imagens(pasta=PASTA_DAS_IMAGENS):
    """
    Grava cada foto da pasta em produtos/<código>.jpg e a liga ao produto do mesmo código.

    Pode rodar quantas vezes for preciso: o arquivo é sobrescrito com o mesmo nome, sem criar
    cópias. Uma foto que alguém trocou pelo Admin é mantida enquanto o arquivo dela existir;
    se o arquivo sumiu (o disco do Render foi recriado), o produto volta a usar a foto da pasta,
    em vez de mostrar uma imagem quebrada. Só o campo imagem é gravado: o saldo de estoque não
    é tocado (ele só muda pelo serviço de estoque).
    """
    resultado = ResultadoDasImagens()
    campo = Produto._meta.get_field("imagem")
    arquivos = {arquivo.stem: arquivo for arquivo in sorted(Path(pasta).glob("*.jpg"))}
    produtos = {produto.codigo: produto for produto in Produto.objects.filter(codigo__in=arquivos)}

    for codigo, arquivo in arquivos.items():
        produto = produtos.get(codigo)
        if produto is None:
            resultado.sem_produto.append(codigo)
            continue

        nome = f"{campo.upload_to}{codigo}.jpg"
        atual = produto.imagem.name
        if atual and atual != nome and campo.storage.exists(atual):
            resultado.mantidas.append(codigo)
            continue

        if campo.storage.exists(nome):
            campo.storage.delete(nome)
        with arquivo.open("rb") as conteudo:
            salvo = campo.storage.save(nome, File(conteudo, name=arquivo.name))
        Produto.objects.filter(pk=produto.pk).update(imagem=salvo)
        resultado.ligadas.append(codigo)

    return resultado
