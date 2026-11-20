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
    source_port: 'Compilado a partir do código-fonte',
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

  /* Colunas empilhadas, de uma ou duas séries, numa escala só a partir de zero.
     opcoes: linhas, series [{valor: fn(linha), classe: 'seg-1'|'seg-2', rotulo}], rotulo(linha, i),
     descricao(linha), dica(linha) -> {titulo, subtitulo, extra?}, titulo (para leitores de tela).
     Devolve a função que redesenha; ela já é chamada de novo quando a janela muda de tamanho. */
  L.colunas = function (plot, o) {
    var NS = 'http://www.w3.org/2000/svg';
    function el(tag, attrs, texto) {
      var n = document.createElementNS(NS, tag);
      for (var k in attrs) n.setAttribute(k, attrs[k]);
      if (texto != null) n.textContent = texto;
      return n;
    }
    function div(classe, texto) { var n = document.createElement('div'); n.className = classe; if (texto != null) n.textContent = texto; return n; }
    function topo(x, y, w, h) {
      var r = Math.min(4, h, w / 2);
      return 'M' + x + ',' + (y + h) + ' L' + x + ',' + (y + r) + ' Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
        ' L' + (x + w - r) + ',' + y + ' Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + ' L' + (x + w) + ',' + (y + h) + ' Z';
    }
    var dica = div('dica');
    dica.hidden = true;
    function total(linha) { return o.series.reduce(function (t, s) { return t + s.valor(linha); }, 0); }
    function mostrar(linha, x, y) {
      var d = o.dica(linha);
      dica.textContent = '';
      dica.appendChild(div('dica__valor', d.titulo));
      dica.appendChild(div('dica__rotulo', d.subtitulo));
      if (o.series.length > 1) o.series.forEach(function (s, i) {
        var l = div('dica__linha');
        var chave = document.createElement('i');
        chave.className = 'chave chave--' + (i + 1);
        l.appendChild(chave);
        var b = document.createElement('b');
        b.textContent = s.valor(linha);
        l.appendChild(b);
        l.appendChild(document.createTextNode(s.rotulo));
        dica.appendChild(l);
      });
      if (d.extra) dica.appendChild(div('dica__linha', d.extra));
      dica.hidden = false;
      var largura = dica.offsetWidth, altura = dica.offsetHeight, folga = 22;
      var direita = x + folga, esquerda = x - folga - largura;
      dica.style.left = Math.max(0, direita + largura <= plot.clientWidth ? direita : esquerda) + 'px';
      dica.style.top = Math.max(0, Math.min(y - 6, plot.clientHeight - altura)) + 'px';
    }
    function desenhar() {
      var linhas = o.linhas;
      plot.textContent = '';
      plot.appendChild(dica);
      var W = Math.max(280, plot.clientWidth), esq = 34, dir = 6, alto = 24, alturaPlot = o.altura || 170, base = 22;
      var H = alto + alturaPlot + base;
      var banda = (W - esq - dir) / Math.max(1, linhas.length);
      var larguraBarra = Math.min(28, Math.max(6, banda * 0.5));
      var maior = Math.max.apply(null, linhas.map(total).concat([1]));
      var passos = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000];
      var passo = passos.filter(function (p) { return maior / p <= 5; })[0] || Math.ceil(maior / 5);
      var teto = Math.ceil(maior / passo) * passo;
      var y = function (v) { return alto + alturaPlot - v / teto * alturaPlot; };
      var desenho = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'group', 'aria-label': o.titulo });
      for (var t = 0; t <= teto; t += passo) {
        desenho.appendChild(el('line', { x1: esq, x2: W - dir, y1: y(t), y2: y(t), 'class': t ? 'grade' : 'eixo' }));
        desenho.appendChild(el('text', { x: esq - 8, y: y(t) + 3.5, 'text-anchor': 'end' }, t));
      }
      var pico = 0;
      linhas.forEach(function (l, i) { if (total(l) > total(linhas[pico])) pico = i; });
      var pular = banda < 34 ? Math.ceil(34 / banda) : 1;
      linhas.forEach(function (linha, i) {
        var soma = total(linha), cx = esq + banda * (i + 0.5), x = cx - larguraBarra / 2;
        var g = el('g', { 'class': 'coluna', tabindex: 0, role: 'img', 'aria-label': o.descricao(linha) });
        g.appendChild(el('rect', { 'class': 'faixa-alvo', x: esq + banda * i, y: alto - 14, width: banda, height: alturaPlot + 14 }));
        /* Segmentos de baixo para cima; 2px da cor da parede entre eles; só a ponta de cima é arredondada */
        var acumulado = 0, visiveis = o.series.filter(function (s) { return s.valor(linha) > 0; });
        visiveis.forEach(function (s, k) {
          var v = s.valor(linha), h = v / teto * alturaPlot, ultimo = k === visiveis.length - 1;
          var vao = visiveis.length > 1 ? (k === 0 || ultimo ? 1 : 2) : 0;
          if (ultimo) g.appendChild(el('path', { 'class': s.classe, d: topo(x, y(acumulado + v), larguraBarra, Math.max(1, h - (k ? 1 : 0))) }));
          else g.appendChild(el('rect', { 'class': s.classe, x: x, y: y(acumulado + v) + vao, width: larguraBarra, height: Math.max(1, h - vao) }));
          acumulado += v;
        });
        if (i === pico && soma > 0) g.appendChild(el('text', { 'class': 'rotulo-valor', x: cx, y: y(soma) - 7, 'text-anchor': 'middle' }, soma));
        if (i % pular === 0) g.appendChild(el('text', { x: cx, y: alto + alturaPlot + 15, 'text-anchor': 'middle' }, o.rotulo(linha, i)));
        var ver = function () { var k = plot.clientWidth / W; mostrar(linha, cx * k, y(soma) * k); };
        g.addEventListener('pointerenter', ver);
        g.addEventListener('focus', ver);
        g.addEventListener('pointerleave', function () { dica.hidden = true; });
        g.addEventListener('blur', function () { dica.hidden = true; });
        desenho.appendChild(g);
      });
      plot.appendChild(desenho);
    }
    desenhar();
    L.aoRedimensionar(desenhar);
    return desenhar;
  };

  /* Liga um botão a uma tabela escondida: "Ver os números em tabela" */
  L.alternarTabela = function (botao, tabela) {
    botao.addEventListener('click', function () {
      tabela.hidden = !tabela.hidden;
      botao.setAttribute('aria-expanded', String(!tabela.hidden));
      botao.textContent = tabela.hidden ? 'Ver os números em tabela' : 'Esconder a tabela';
    });
  };
  L.aoRedimensionar = function (fn) {
    var espera;
    window.addEventListener('resize', function () { clearTimeout(espera); espera = setTimeout(fn, 120); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fn);
  };

  return L;
})();
