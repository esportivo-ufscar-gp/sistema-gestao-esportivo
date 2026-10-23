from unittest import mock

from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_responde_ok_quando_banco_esta_disponivel(self):
        resposta = self.client.get(reverse("core:health"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"status": "ok", "banco_de_dados": "ok"})

    def test_responde_503_quando_banco_esta_indisponivel(self):
        with mock.patch("apps.core.views.banco_disponivel", return_value=False):
            resposta = self.client.get(reverse("core:health"))

        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.json()["banco_de_dados"], "indisponível")


class HomeTests(TestCase):
    def test_pagina_inicial_usa_o_template_base(self):
        resposta = self.client.get(reverse("core:home"))

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "core/home.html")
        self.assertTemplateUsed(resposta, "base.html")
