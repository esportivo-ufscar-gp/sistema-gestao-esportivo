"""
Leitura das variáveis de ambiente usadas pelo config/settings.py.

Fica num módulo à parte para poder ser testada: cada função recebe o ambiente (um dicionário,
por padrão os.environ) e devolve o valor da configuração.

Pacote 3.3 (ambiente de demonstração): além das variáveis do .env, entende as que o Render
define sozinho (RENDER, RENDER_EXTERNAL_HOSTNAME, RENDER_EXTERNAL_URL) e a DATABASE_URL que o
banco do Render entrega ao site.
"""
import os
from urllib.parse import parse_qsl, unquote, urlsplit

ESQUEMAS_DO_POSTGRESQL = ("postgres", "postgresql")


def env_bool(nome, padrao=False, ambiente=None):
    ambiente = os.environ if ambiente is None else ambiente
    return str(ambiente.get(nome, padrao)).strip().lower() in ("1", "true", "sim", "yes")


def env_list(nome, padrao="", ambiente=None):
    ambiente = os.environ if ambiente is None else ambiente
    return [item.strip() for item in ambiente.get(nome, padrao).split(",") if item.strip()]


def banco_de_dados(base_dir, ambiente=None):
    """
    Configuração do banco "default".

    Em ordem: DATABASE_URL (o Render entrega só a string de conexão), DB_ENGINE=sqlite (atalho
    local) ou as variáveis DB_NAME, DB_USER, DB_PASSWORD, DB_HOST e DB_PORT do .env.
    """
    ambiente = os.environ if ambiente is None else ambiente

    url = ambiente.get("DATABASE_URL", "").strip()
    if url:
        return banco_da_url(url)

    if ambiente.get("DB_ENGINE", "postgresql") == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3"}

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": ambiente.get("DB_NAME", "esportivo"),
        "USER": ambiente.get("DB_USER", "postgres"),
        "PASSWORD": ambiente.get("DB_PASSWORD", ""),
        "HOST": ambiente.get("DB_HOST", "localhost"),
        "PORT": ambiente.get("DB_PORT", "5432"),
    }


def banco_da_url(url):
    """
    Converte postgresql://usuario:senha@host:porta/banco?sslmode=require na configuração do Django.

    Os parâmetros depois do "?" (como sslmode) vão para OPTIONS, que o psycopg repassa ao
    PostgreSQL. Só o PostgreSQL é aceito: é o banco oficial do projeto (CLAUDE.md).
    """
    partes = urlsplit(url)
    if partes.scheme not in ESQUEMAS_DO_POSTGRESQL:
        raise ValueError(f"DATABASE_URL precisa ser do PostgreSQL (postgresql://...), não {partes.scheme}://.")

    configuracao = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(partes.path.lstrip("/")),
        "USER": unquote(partes.username or ""),
        "PASSWORD": unquote(partes.password or ""),
        "HOST": partes.hostname or "",
        "PORT": str(partes.port or 5432),
    }
    opcoes = dict(parse_qsl(partes.query))
    if opcoes:
        configuracao["OPTIONS"] = opcoes
    return configuracao


def enderecos_publicos(ambiente=None):
    """
    ALLOWED_HOSTS e CSRF_TRUSTED_ORIGINS.

    Junta o que vem do .env com o endereço que o Render dá ao site (algo.onrender.com), para o
    deploy funcionar sem ninguém precisar copiar o endereço para uma variável. Sem a origem
    https:// em CSRF_TRUSTED_ORIGINS, todo formulário (login, carrinho, checkout) daria erro 403.
    """
    ambiente = os.environ if ambiente is None else ambiente

    hosts = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1", ambiente)
    origens = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "", ambiente)

    host_do_render = ambiente.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if host_do_render and host_do_render not in hosts:
        hosts.append(host_do_render)

    url_do_render = ambiente.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not url_do_render and host_do_render:
        url_do_render = f"https://{host_do_render}"
    if url_do_render and url_do_render not in origens:
        origens.append(url_do_render)

    return hosts, origens
