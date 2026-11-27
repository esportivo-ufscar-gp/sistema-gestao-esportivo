#!/usr/bin/env bash
# Build do Render (pacote 3.3, ambiente de demonstração), chamado pelo render.yaml a cada deploy.
#
# O plano gratuito do Render não tem terminal nem comando de pré-deploy, então as migrações e a
# carga dos dados de demonstração rodam aqui, como no guia de Django do próprio Render.
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Idempotente: reaplica as permissões de cada perfil, caso um pacote novo tenha mudado o mapa.
python manage.py criar_perfis

# Só carrega os dados no primeiro deploy; depois, o banco já tem vendas e o comando não faz nada.
# A senha vem de DEMO_SENHA, preenchida no painel do Render.
python manage.py popular_demonstracao --se-vazio
