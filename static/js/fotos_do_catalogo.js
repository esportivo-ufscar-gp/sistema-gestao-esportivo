/* Troca das fotos no cartão do catálogo (pacote 3.3).
 *
 * Com o mouse sobre o cartão, depois de ESPERA_MS (para não piscar quando o mouse só atravessa
 * o cartão ao rolar a página), as fotos passam a trocar a cada INTERVALO_MS: a principal e as
 * extras, em ordem, com pontos que mostram qual está aparecendo. Quando o mouse sai, volta para
 * a principal.
 *
 * Só age em cartões com o atributo data-fotos-do-produto (produto com fotos extras). Não faz
 * nada em telas sem hover (celular) nem com "reduzir movimento" ligado no sistema: nesses casos,
 * e sem JavaScript, aparece só a foto principal.
 */
(function () {
  "use strict";

  const ESPERA_MS = 300;
  const INTERVALO_MS = 1000;

  const temHover = window.matchMedia("(hover: hover) and (pointer: fine)");
  const reduzirMovimento = window.matchMedia("(prefers-reduced-motion: reduce)");

  function prepararCartao(caixa) {
    const fotos = Array.from(caixa.querySelectorAll(".cartao-produto__foto"));
    const pontos = Array.from(caixa.querySelectorAll(".cartao-produto__ponto"));
    const cartao = caixa.closest(".cartao-produto") || caixa;
    let atual = 0;
    let espera = null;
    let troca = null;

    function mostrar(indice) {
      if (indice === atual) {
        return;
      }
      fotos[atual].hidden = true;
      fotos[indice].hidden = false;
      pontos[atual]?.classList.remove("ativo");
      pontos[indice]?.classList.add("ativo");
      atual = indice;
    }

    // Uma foto que ainda não carregou (ou cujo arquivo sumiu) é pulada, em vez de deixar o
    // cartão em branco; ela entra na volta seguinte, se tiver carregado.
    function pronta(foto) {
      return foto.complete && foto.naturalWidth > 0;
    }

    function proxima() {
      for (let passo = 1; passo < fotos.length; passo += 1) {
        const indice = (atual + passo) % fotos.length;
        if (pronta(fotos[indice])) {
          mostrar(indice);
          return;
        }
      }
    }

    function comecar() {
      if (!temHover.matches || reduzirMovimento.matches) {
        return;
      }
      // As extras têm loading="lazy" e estão escondidas: começam a carregar aqui, durante a espera.
      fotos.forEach(function (foto) {
        foto.loading = "eager";
      });
      espera = window.setTimeout(function () {
        caixa.classList.add("trocando");
        proxima();
        troca = window.setInterval(proxima, INTERVALO_MS);
      }, ESPERA_MS);
    }

    function parar() {
      window.clearTimeout(espera);
      window.clearInterval(troca);
      espera = null;
      troca = null;
      caixa.classList.remove("trocando");
      mostrar(0);
    }

    cartao.addEventListener("mouseenter", comecar);
    cartao.addEventListener("mouseleave", parar);
  }

  document.querySelectorAll("[data-fotos-do-produto]").forEach(prepararCartao);
})();
