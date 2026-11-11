/* Funções que a vitrine e o observatório dividem: textos, datas e a regra da luz de status. */
window.LOKGAM = (function () {
  'use strict';
  var L = {};

  L.esc = function (s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  L.plural = function (n, um, varios) { return n + ' ' + (n === 1 ? um : varios); };
  L.lista = function (a) { return a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' e ' + a[a.length - 1]; };

  L.ESTADO = { online: 'No ar', unstable: 'Instável', offline: 'Fora do ar', unverified: 'Não conferido' };
  L.ESTADO_CURTO = { online: 'no ar', unstable: 'instável', offline: 'fora do ar', unverified: 'não conferido' };
  L.TIPO = { launch: 'Lançamento', dmca_notice: 'Notificação de direitos autorais', removal: 'Remoção', outage: 'Queda', restored: 'Voltou ao ar', model_change: 'Mudou de modelo' };
  L.TECNICA = {
    native_web: 'Feito para a web',
    source_port: 'Compilado do código-fonte aberto',
    reimplementation: 'Motor reescrito do zero',
    decompilation: 'Código reconstruído por engenharia reversa',
    recompilation: 'Recompilação estática do código original',
    emulation: 'Emulação no navegador',
    unknown: 'Ainda não identificada'
  };
  L.MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  /* "2026-11-10" vira 10/11/2026, "2026-09" vira set/2026, "2015" fica 2015 */
  L.data = function (s) {
    if (!s) return '';
    var p = s.slice(0, 10).split('-');
    if (p[2]) return p[2] + '/' + p[1] + '/' + p[0];
    if (p[1]) return L.MES[+p[1] - 1] + '/' + p[0];
    return p[0];
  };
  /* Data só com mês vai para o fim daquele mês na ordenação */
  L.chave = function (d) { return d.length === 7 ? d + '-99' : d; };
  L.temHora = function (s) { return s.length > 10; };
  L.instante = function (s) { return Date.parse(L.temHora(s) ? s : s + 'T12:00:00Z'); };
  L.dataHora = function (s) {
    if (!L.temHora(s)) return L.data(s);
    return new Date(s).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  };
  L.idadeCurta = function (ms) {
    var min = Math.max(0, Math.round(ms / 60000));
    if (min < 1) return 'agora';
    if (min < 60) return min + ' min';
    var h = Math.round(min / 60);
    return h < 48 ? h + ' h' : Math.round(h / 24) + ' d';
  };
  L.ha = function (ms) {
    var curta = L.idadeCurta(ms);
    return curta === 'agora' ? 'agora há pouco' : 'há ' + curta;
  };
  /* Quando foi uma conferência: "há 3 h", ou "em 10/11" se ela só tem o dia */
  L.quando = function (check, agora, curto) {
    if (!check) return '';
    if (!L.temHora(check.checked_at)) {
      var p = check.checked_at.split('-');
      return (curto ? '' : 'em ') + p[2] + '/' + p[1];
    }
    var ms = agora - Date.parse(check.checked_at);
    return curto ? L.idadeCurta(ms) : L.ha(ms);
  };

  /* A regra da luz. Vale a última conferência que de fato viu o site, e ela vale
     por 72 horas. Depois disso, ou sem nenhuma, a luz volta para "não conferido":
     a página nunca afirma o estado de agora com base em dado velho. */
  L.VALIDADE_MS = 72 * 3600 * 1000;
  L.situacao = function (item, agora) {
    var visto = item.seen;
    if (visto && agora - L.instante(visto.checked_at) <= L.VALIDADE_MS) return { state: visto.state, check: visto, vencida: false };
    return { state: 'unverified', check: visto || item.last || null, vencida: !!visto };
  };

  /* Faixa de conferências, da mais antiga para a mais recente. `vagas` completa
     com traços à esquerda para todas as faixas de uma lista terem o mesmo tamanho. */
  L.faixa = function (historico, vagas) {
    var caixa = document.createElement('span');
    caixa.className = 'faixa';
    caixa.setAttribute('role', 'img');
    var conta = { online: 0, unstable: 0, offline: 0, unverified: 0 };
    for (var i = historico.length; i < (vagas || 0); i++) {
      var vazio = document.createElement('i');
      vazio.className = 'pulso pulso--vazio';
      caixa.appendChild(vazio);
    }
    historico.forEach(function (h) {
      var b = document.createElement('i');
      b.className = 'pulso pulso--' + h[1];
      b.title = L.dataHora(h[0]) + ': ' + L.ESTADO_CURTO[h[1]];
      conta[h[1]]++;
      caixa.appendChild(b);
    });
    var partes = Object.keys(conta).filter(function (k) { return conta[k]; }).map(function (k) { return conta[k] + ' ' + L.ESTADO_CURTO[k]; });
    caixa.setAttribute('aria-label', historico.length
      ? L.plural(historico.length, 'conferência', 'conferências') + ': ' + L.lista(partes)
      : 'Nenhuma conferência ainda');
    return caixa;
  };

  /* Letreiro: mantém a letra na largura máxima e ajusta o tamanho para ocupar a linha */
  L.ajustarLetreiro = function (el, maximo) {
    var letras = el.firstElementChild;
    el.style.fontSize = '';
    var fs = parseFloat(getComputedStyle(el).fontSize);
    var w = letras.getBoundingClientRect().width;
    if (w > 0) el.style.fontSize = Math.min(fs * el.clientWidth / w * 0.992, maximo || 190) + 'px';
  };

  L.aCadaMinuto = function (fn) { fn(); setInterval(fn, 60000); };
  L.aoRedimensionar = function (fn) {
    var espera;
    window.addEventListener('resize', function () { clearTimeout(espera); espera = setTimeout(fn, 120); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fn);
  };

  return L;
})();
