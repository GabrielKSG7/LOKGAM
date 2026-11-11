# LOKGAM

Locadora de games no navegador.

Catálogo de jogos de console que rodam direto no navegador, no espírito do Click Jogos e do FRIV, com uma diferença: cada jogo tem uma ficha que diz o que o port distribui, o que o jogador precisa ter e qual o risco de ele sumir.

Este repositório é um protótipo.

## O que tem aqui

```
data/ports.json      fichas dos ports (uma por port, não por jogo)
data/events.json     fatos datados: lançamentos, notificações, remoções, quedas
data/checks.jsonl    conferências de link, uma linha por conferência
schema/              JSON Schema das três tabelas
scripts/validate.py  valida formato e regras de curadoria
scripts/build.py     gera docs/index.html com a base embutida
web/template.html    a vitrine (HTML, CSS e JS em um arquivo)
docs/index.html      página gerada, pronta para o GitHub Pages
```

## Modelo de dados

Três tabelas, ligadas por `ports.id`.

| Tabela | Grão | Muda como | Para que serve |
|---|---|---|---|
| `ports` | um port (jogo + quem publicou + endereço) | editada pela curadoria | a ficha que aparece na vitrine |
| `events` | um fato datado sobre um port | só cresce | histórico de quedas e linha do tempo da ficha |
| `checks` | uma conferência de link | só cresce | a luz de status na capa e, depois, o tempo de vida de cada port |

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

## Como rodar

```
pip install -r requirements.txt
python3 scripts/validate.py
python3 scripts/build.py
```

O `build.py` valida a base e grava `docs/index.html`. Para publicar no GitHub Pages, aponte o Pages para a pasta `docs/` do branch principal.

## Como adicionar um port

1. Acrescente a ficha em `data/ports.json`. Se ainda faltar confirmar de onde vêm os dados do jogo, use `curation.state: "pending"` e `rights.status: "unknown"`.
2. Registre a conferência do link em `data/checks.jsonl`.
3. Se houver lançamento, notificação ou queda com fonte, registre em `data/events.json`.
4. Rode `python3 scripts/build.py`.

## Estado da base

Fichas conferidas em 10/11/2026: 11 aprovadas, 1 em análise e 6 rejeitadas, com 10 eventos. Das aprovadas, 5 tiveram o link aberto na conferência; nas outras 6 o endereço veio das fontes citadas na ficha e ainda não foi aberto.

## Próximos passos

- Conferência automática de links (GitHub Actions) gravando em `checks.jsonl`.
- Observatório: quanto tempo cada port fica no ar, por técnica, selo e dono do jogo, a partir de `events` e `checks`.
- Fichas de jogos comerciais (Budokai, PES e afins) seguindo a política acima.
- Envio de jogos por formulário, que cai na fila "Em análise" e só entra na vitrine depois de aprovado.
- Canal para corrigir ou pedir a remoção de uma ficha.
- Domínio próprio.

## Ideias para o futuro

- **Launcher próprio**: guardar a biblioteca de arquivos do jogador uma vez só, dizer quais ports aceitam cada arquivo, padronizar controle e tela cheia, jogar offline e abrir só sites curados. Começaria como app instalável a partir do site.
- **Smart TVs**: verificar se a vitrine e os ports rodam nos navegadores de TV (Tizen, webOS, Android TV), que costumam ter suporte limitado a WebAssembly, WebGL 2 e controles. A vitrine precisaria de navegação pelo controle remoto.

## Avisos

A Locadora não hospeda jogos: cada ficha leva ao site do próprio projeto. Jogos, nomes e marcas pertencem aos seus donos.
