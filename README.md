# LOKGAM

Locadora de games no navegador: um catálogo de jogos de console que rodam direto no navegador, no espírito do Click Jogos e do FRIV. A diferença é que cada jogo tem uma ficha que diz o que o port distribui, o que o jogador precisa ter e qual o risco de ele sumir, e um robô confere quatro vezes por dia se cada link continua no ar.

- **Vitrine:** https://gabrielksg7.github.io/LOKGAM/
- **Observatório:** https://gabrielksg7.github.io/LOKGAM/observatorio/

O projeto é um protótipo em evolução.

## Como funciona

```
data/*.json(l)  ──►  validate.py  ──►  build.py  ──►  docs/ (GitHub Pages)
      ▲                                   ▲
      │                                   │
check_links.py (robô, a cada 6 h)     metrics.py (observatório)
```

A base são três arquivos de texto versionados no Git. O robô acrescenta linhas, as métricas são recalculadas e o site é gerado de novo, tudo no GitHub Actions. Não há servidor nem banco de dados.

```
data/ports.json         fichas dos ports (uma por port, não por jogo)
data/events.json        fatos datados: lançamentos, notificações, remoções, quedas
data/checks.jsonl       conferências de link, uma linha por conferência
schema/                 JSON Schema das três tabelas
scripts/validate.py     valida formato e regras de curadoria
scripts/check_links.py  o robô de conferência
scripts/metrics.py      métricas do observatório
scripts/build.py        gera docs/ a partir da base e de web/
web/                    modelos das páginas, CSS e JS compartilhados
tests/                  testes (pytest)
docs/                   site gerado; não edite à mão
```

## Modelo de dados

Três tabelas, ligadas por `ports.id`.

| Tabela | Grão | Muda como | Para que serve |
|---|---|---|---|
| `ports` | um port (jogo + quem publicou + endereço) | editada pela curadoria | a ficha que aparece na vitrine |
| `events` | um fato datado sobre um port | só cresce | histórico de quedas e linha do tempo da ficha |
| `checks` | uma conferência de link | só cresce | a luz de status na capa e a disponibilidade no observatório |

Os campos que sustentam a curadoria ficam em `ports`:

| Campo | Valores | O que significa |
|---|---|---|
| `rights.status` | `official`, `free`, `demo`, `byo_files`, `bundled`, `unknown` | o que o port distribui e com que direito |
| `port.technique` | `native_web`, `source_port`, `reimplementation`, `decompilation`, `recompilation`, `emulation`, `unknown` | como o jogo chegou ao navegador |
| `curation.state` | `approved`, `pending`, `rejected` | se a ficha aparece na vitrine |
| `curation.risk` | `low`, `medium`, `high` | avaliação editorial do risco de remoção |
| `requirements.user_files` | lista | arquivos que o jogador precisa fornecer, e para quê |
| `label` | forma, cor e estampa | a capa gerada pela página, já que arte oficial não é usada |

A descrição de cada campo está nos arquivos de `schema/`.

## Regras de curadoria

O `validate.py` recusa a base se alguma destas regras falhar:

- Ficha aprovada tem link para jogar, selo listável (`official`, `free`, `demo` ou `byo_files`), técnica conhecida, risco avaliado, capa e pelo menos uma conferência de link.
- Selo `byo_files` exige um arquivo marcado como necessário para jogar. Selo `demo` exige um arquivo que libere o jogo completo.
- Port que embute o jogo de terceiros (`bundled`) só existe como ficha rejeitada.
- Ficha rejeitada não guarda link para jogar. O port continua na base por causa dos eventos, que alimentam o histórico de quedas.

O risco é uma avaliação editorial, não um parecer jurídico.

### Jogos comerciais (Budokai, PES e afins)

Entram na base, com duas condições:

- **Com link** só quando o port pede os arquivos da cópia do jogador (selo "Sua cópia").
- **Sem link** quando o port já vem com o jogo dentro. A ficha fica registrada como informativa e alimenta o histórico de quedas e o observatório.

## O robô de conferência

O `check_links.py` abre a página de cada port que tem link guardado (fichas aprovadas e em análise), lê só o começo da resposta e grava uma linha por port em `checks.jsonl`. Ele se identifica como `LOKGAM-conferencia`, com o endereço deste repositório, e não tenta se passar por navegador.

Cada conferência tem um **estado**, que é o que a luz da capa mostra, e um **motivo**, que é o que a análise usa:

| A resposta | Estado | Motivo |
|---|---|---|
| 2xx | `online` | `ok` |
| 401, 403, 429 ou desafio contra robôs | `unverified` | `bot_blocked` |
| 404 ou 410 | `offline` | `not_found` |
| 451 | `offline` | `legal_block` |
| Endereço que não resolve | `offline` | `dns_error` |
| 5xx | `unstable` | `server_error` |
| Sem resposta a tempo, conexão recusada, certificado inválido | `unstable` | `timeout`, `connection_error`, `tls_error` |
| 2xx em página curta que diz que o jogo foi removido | `unstable` | `takedown_notice` |

Decisões que valem saber:

- **Site que barra o robô não é site fora do ar.** A conferência fica como "não conferido" e não entra na conta de disponibilidade.
- **Falha passageira ganha mais duas tentativas.** Bloqueio, 404 e aviso de remoção não: insistir não muda a resposta.
- **Aviso de remoção pede conferência à mão.** O robô marca como instável e avisa na ficha, em vez de declarar o port morto sozinho.
- **Robô sem rede não grava nada.** Se todas as conferências de uma passagem falharem por erro de rede, o script sai com erro e a base fica como estava.

Na página, vale a última conferência que de fato viu o site, e ela vale por 72 horas. Depois disso a capa volta para "não conferido": a vitrine nunca afirma o estado de agora com base em dado velho.

## O observatório

O `metrics.py` calcula, a partir das três tabelas:

- **Disponibilidade por port:** conferências com resposta normal, divididas pelas conferências em que o robô viu o site. A porcentagem só aparece depois de 8 conferências válidas.
- **Notificações e quedas por mês:** eventos com fonte, separados em ação de dono de jogo (notificação ou remoção) e queda.
- **Quem agiu:** donos de jogos que notificaram ou removeram ports.
- **Raio-x da base:** fichas por técnica de port e por estado de curadoria.

Um limite de propósito: a LOKGAM não guarda link de port que embute o jogo, então esses ports não são conferidos pelo robô. O que se sabe deles vem de notícias e entra como evento.

## Como rodar

```
pip install -r requirements-dev.txt
python3 scripts/validate.py                 # valida a base
pytest                                      # roda os testes
python3 scripts/check_links.py --dry-run    # confere os links sem gravar
python3 scripts/build.py                    # gera docs/
```

Os testes do robô sobem um servidor HTTP local e exercitam cada tipo de resposta, sem depender da internet.

## Automação

| Workflow | Quando roda | O que faz |
|---|---|---|
| `conferir-links.yml` | a cada 6 horas e sob demanda | confere os links, gera o site e grava tudo em um commit |
| `ci.yml` | a cada push e pull request | valida a base, roda os testes e confere se `docs/` está em dia |

Para rodar a conferência na hora: aba **Actions**, workflow **Conferir links**, botão **Run workflow**.

## Como adicionar um port

1. Acrescente a ficha em `data/ports.json`. Se ainda faltar confirmar de onde vêm os dados do jogo, use `curation.state: "pending"` e `rights.status: "unknown"`.
2. Registre uma conferência manual em `data/checks.jsonl`, ou deixe o robô passar.
3. Se houver lançamento, notificação ou queda com fonte, registre em `data/events.json`.
4. Rode `python3 scripts/build.py` e inclua `docs/` no commit.

## Próximos passos

- Fichas de jogos comerciais (Budokai, PES e afins) seguindo a política acima.
- Envio de jogos por formulário, que cai na fila "Em análise" e só entra na vitrine depois de aprovado.
- Canal para corrigir ou pedir a remoção de uma ficha.
- Observatório: tempo entre o lançamento e a notificação, e tempo de resposta dos sites.
- Domínio próprio.

## Ideias para o futuro

- **Launcher próprio:** guardar a biblioteca de arquivos do jogador uma vez só, dizer quais ports aceitam cada arquivo, padronizar controle e tela cheia, jogar offline e abrir só sites curados. Começaria como app instalável a partir do site.
- **Smart TVs:** verificar se a vitrine e os ports rodam nos navegadores de TV (Tizen, webOS, Android TV), que costumam ter suporte limitado a WebAssembly, WebGL 2 e controles. A vitrine precisaria de navegação pelo controle remoto.

## Avisos

A LOKGAM não hospeda jogos: cada ficha leva ao site do próprio projeto. Jogos, nomes e marcas pertencem aos seus donos.
