# CLAUDE.md

Guia para quem (humano ou Claude) for mexer neste projeto depois.

## O que é o projeto

Programa desktop (Tkinter) para baixar vídeos do YouTube em MP4 e salvar
direto numa pasta/pendrive, para tocar no som/multimídia do carro. Uso
pessoal do dono do projeto, não é distribuído nem publicado.

- Usuário final: leigo, só usa o `.bat` e a janela. Não abre terminal.
- Prioridade #1: **compatibilidade com rádio de carro** — MP4 com
  H.264 + AAC, nomes de arquivo sem exigir acento/caractere especial,
  ordenação correta de playlist por número no nome do arquivo.
- Prioridade #2: não travar/perder a lista inteira por causa de 1 vídeo
  com problema (privado, removido, etc.) — sempre seguir em frente e
  reportar no fim.

## Stack e arquivos

- Python 3 + Tkinter (biblioteca padrão, sem framework de UI extra).
- `yt-dlp` para extração/baixa dos vídeos.
- `imageio-ffmpeg` só para fornecer o binário do `ffmpeg` embutido (não
  precisa instalar nada separado no Windows).
- Tudo num arquivo só: `meu_downloader.py`. Projeto pequeno o suficiente
  pra não justificar quebrar em módulos — repensar isso se passar de uns
  800-1000 linhas.

Arquivos:
- `meu_downloader.py` — programa inteiro.
- `Abrir Downloader.bat` — atalho que o usuário final clica (ativa o
  `.venv` e roda o script).
- `requirements.txt` — `yt-dlp`, `imageio-ffmpeg`.
- `README.md` — manual do usuário final, em português simples. Qualquer
  feature nova visível na janela precisa de uma entrada lá.
- `.venv/` — ambiente virtual já criado, não versionar/mexer à toa.
- `config.json` — gerado em runtime ao lado do script (preferências do
  usuário). Não existe no repo recém-clonado; não precisa versionar.
- `.downloader_historico.txt` — gerado em runtime **dentro de cada pasta
  de destino** escolhida pelo usuário (não fica na pasta do projeto).
  Guarda os IDs de vídeo já baixados ali, para a opção "pular duplicados".

## Como rodar / testar

Não tem suite de testes automatizada (é um programa de UI pequeno, de uso
pessoal). O jeito usado durante o desenvolvimento para validar mudanças
sem abrir a janela toda vez:

```powershell
.\.venv\Scripts\python.exe -c "import ast; ast.parse(open('meu_downloader.py', encoding='utf-8').read())"  # sintaxe
.\.venv\Scripts\python.exe -c "import meu_downloader"  # import limpo
```

Para testar lógica de download sem clicar na UI, instanciar `App` "a seco"
(sem rodar `__init__`) e chamar os métodos internos direto, passando uma
fila e um destino de teste:

```python
import queue, threading
import meu_downloader as m
app = object.__new__(m.App)
app.fila_mensagens = queue.Queue()
app.parar_flag = threading.Event()
opcoes = {...}  # ver App._iniciar_download para as chaves esperadas
app._baixar_tudo(["https://www.youtube.com/watch?v=jNQXAC9IVRw"], "C:/caminho/de/teste", opcoes)
```

Isso baixa de verdade (sem mock) — útil porque esse projeto depende muito
de comportamento real do yt-dlp (extração, merge, nomes de arquivo) que não
vale a pena mockar. Para testar a janela em si, instanciar `App(tk.Tk())`
e chamar `root.update()`; para testar o fechamento de verdade, usar
`root.mainloop()` com um `root.after(...)` agendando o fechamento (chamar
`destroy()` fora do mainloop solto dispara um erro cosmético de `after`
pendente — não é bug do programa, é só do script de teste).

Usar sempre um vídeo curto e público para teste real (ex.: "Me at the zoo",
`jNQXAC9IVRw`) para não gastar tempo/banda.

## Arquitetura do código

`meu_downloader.py` tem duas partes:

1. **Funções module-level, sem estado** (fáceis de testar isoladas):
   `limpar_titulo`, `montar_formato`, `montar_outtmpl`, `exemplo_nome`,
   `carregar_config`/`salvar_config`, `carregar_historico`/
   `registrar_historico`. Qualquer lógica nova que não precise da UI deve
   nascer aqui, não dentro da classe `App`.
2. **Classe `App`** — a janela. Fluxo principal:
   - `_iniciar_download` (thread principal/UI) valida input, monta
     `opcoes` (dict) e sobe uma thread para `_baixar_tudo` (fluxo direto)
     ou `_coletar_e_revisar` (quando "Mostrar lista pra escolher o que
     baixar" está marcado).
   - `_coletar_itens` (thread de trabalho) faz uma pré-varredura
     (`extract_flat`) de todos os links colados, identifica playlists,
     achata playlist-de-playlist (`_achatar_entradas`), remove duplicados
     (`_remover_repetidos`) e devolve `(itens, falhas_leitura)` — uma
     lista de vídeos individuais + os links que nem puderam ser lidos.
   - `_baixar_tudo` (thread de trabalho) chama `_coletar_itens` e passa o
     resultado pra `_baixar_itens`. `_coletar_e_revisar` faz o mesmo mas,
     em vez de baixar direto, manda uma mensagem `revisar` pra fila —
     quem decide o que baixar é o usuário, na tela aberta por
     `_abrir_selecao` (thread da UI); ao confirmar, ela mesma sobe uma
     thread nova pra `_baixar_itens` só com os itens marcados.
   - `_baixar_itens` (thread de trabalho) é quem de fato percorre os
     itens, monta `ydl_opts` por vídeo (nome de arquivo, formato,
     metadados, normalização de volume etc.), baixa um por um com
     `YoutubeDL`, e manda mensagens pra `fila_mensagens`. Tanto o fluxo
     direto quanto o com revisão terminam aqui — é o único lugar que
     efetivamente baixa algo.
   - **Toda comunicação da thread de trabalho pra UI é via
     `self.fila_mensagens` (uma `queue.Queue`)** — nunca mexer em widget
     Tk direto de dentro de `_baixar_itens`/`_coletar_itens`/
     `_coletar_e_revisar`, porque Tkinter não é thread-safe. Exceção:
     `_abrir_selecao` e os callbacks dela (`confirmar`/`cancelar`) já
     rodam na thread da UI (chamados via `_processar_fila`), então esses
     sim podem mexer em widget direto e até subir thread nova.
     `_processar_fila` (rodando no `root.after`, thread da UI) é quem de
     fato atualiza log/status/progresso/botões.
   - Tipos de mensagem na fila: `log`, `status`, `progress_max`,
     `progress_step`, `falhas` (lista de URLs que falharam, pro botão de
     copiar), `revisar` (tupla `(itens, falhas_leitura, destino, opcoes)`,
     abre a tela de seleção), `fim` (resumo final).

### Convenções

- Nomes de função/variável/comentário em **português**, sem acento (o
  arquivo não força um encoding específico no editor do usuário final,
  então evita problema bobo de exibição). Strings exibidas na janela/log
  também sem acento, pelo mesmo motivo e porque o próprio app tem um modo
  "nomes simples" pra isso.
- Métodos privados de `App` prefixados com `_`.
- Dict `opcoes` é a forma padrão de passar configuração da UI pra thread
  de trabalho — ao adicionar uma opção nova, ela entra em três lugares:
  `tk.BooleanVar`/`StringVar` no `__init__`, o dict `opcoes` em
  `_iniciar_download`, e os métodos `_carregar_preferencias`/
  `_salvar_preferencias` (senão a opção não persiste entre sessões).

## Decisões e armadilhas já descobertas (não repetir)

- **`trim_file_name` do yt-dlp corta o caminho inteiro**, não só o nome do
  arquivo — em destino com caminho longo o arquivo pode acabar salvo fora
  da pasta escolhida. Por isso o limite de tamanho de título é feito à mão
  em `AjustarTituloPP` (só no campo `title`, antes do nome ser montado),
  não com essa opção do yt-dlp.
- **`%` literal em pasta/nome precisa virar `%%`** no `outtmpl` do yt-dlp
  (senão ele tenta interpretar como campo de template). Nome de playlist
  tipo `"Sertanejo 100% Raiz"` já foi usado como caso de teste.
- **yt-dlp já evita sobrescrever arquivo existente por padrão**
  (`nooverwrites`), mas isso é por *nome de arquivo* — não serve como
  "pular duplicado" de verdade, porque muda se o padrão de nome mudar.
  Por isso existe o histórico próprio (`.downloader_historico.txt`,
  guardando `id` do vídeo) em vez de depender só desse comportamento.
  Quando "pular duplicados" está desmarcado, setamos `overwrites: True`
  explicitamente pra garantir que regrava mesmo com nome igual.
- **Falhas de pré-varredura (`_coletar_itens`) e falhas de download
  (`_baixar_tudo`) são duas fontes diferentes** — um vídeo indisponível
  pode falhar já na extração (nunca vira um "item" a baixar) ou falhar
  durante o download de fato. As duas precisam alimentar a mesma lista
  final de falhas (resumo + botão "Copiar links que falharam"); já rolou
  de esquecer a primeira fonte e o botão ficar incompleto — testar sempre
  com um link de vídeo removido/privado junto de um válido.
- Dedupe de link repetido (`_remover_repetidos`) usa o `id` do vídeo, não
  a URL crua — precisa pra pegar `youtube.com/watch?v=X`, `youtu.be/X` e
  variantes com parâmetro extra como o mesmo vídeo.
- **`imageio-ffmpeg` só traz o binário `ffmpeg`, não o `ffprobe`** — o
  postprocessor `EmbedThumbnail` do yt-dlp (capa embutida no arquivo)
  precisa de `ffprobe` e falha com `ffprobe not found` sem ele. Testado e
  confirmado antes de desistir dessa parte. `FFmpegMetadata` (metadados de
  texto: título/artista/data) funciona numa boa sem `ffprobe` — é só isso
  que está implementado hoje. Se precisar de `ffprobe` no futuro (capa
  embutida, ou qualquer outro postprocessor que probe o arquivo), trocar
  `imageio-ffmpeg` por algo como `static-ffmpeg` (traz os dois binários) —
  mas isso muda `requirements.txt` e exige recriar o `.venv` já instalado.
- **Reencodar áudio com filtro (`loudnorm` etc.) não pode ser feito via
  `postprocessor_args` do yt-dlp de forma simples** — a sintaxe por
  postprocessor é confusa e arriscada de acertar sem testar bastante. Mais
  simples e controlável: deixar o yt-dlp terminar tudo (merge, metadata,
  mover pro destino) e aplicar o `ffmpeg` numa segunda passada, direto no
  arquivo final, via `PostProcessor` customizado com `when="after_move"`
  (ver `NormalizarVolumePP`) chamando `subprocess.run` com `-c:v copy`
  (mantém o vídeo intacto) e só re-encoda o áudio.

## Funcionalidades já implementadas

- Download em lote (colar lista ou importar `.txt`), MP4 H.264+AAC,
  escolha de qualidade (480p/720p/1080p/melhor).
- Identificação automática de playlist (inclusive playlist-de-playlist,
  tipo página de canal), com log de quantos vídeos tem, numeração por
  posição e subpasta opcional por playlist.
- Padrão de nome de arquivo configurável (6 opções, com exemplo ao vivo na
  janela) + "nomes simples" (sem acento/espaço) + "limpar títulos" (remove
  `(Official Video)`, `[Clipe Oficial]`, `(HD)` etc. sem nunca esvaziar o
  título).
- Pular vídeo já baixado antes (histórico por pasta de destino) e ignorar
  link repetido na lista colada.
- Preferências (pasta, qualidade, padrão de nome, checkboxes) salvas em
  `config.json` e recarregadas ao abrir.
- Botões "Limpar log" e "Copiar links que falharam".
- Continua a lista mesmo se um vídeo falhar; botão "Parar" interrompe
  entre um vídeo e outro (inclusive durante a tela de revisão, abaixo).
- Normalização de volume (ffmpeg `loudnorm`, só re-encoda áudio) e
  metadados de texto (título/artista/data/link) embutidos no arquivo —
  ambos opcionais, default ligado.
- Tela de revisão opcional ("Mostrar lista pra escolher o que baixar antes
  de começar"): checklist com todos os vídeos encontrados antes de baixar
  de fato, pra escolher quais quer.

## Plano de desenvolvimento — próximas features (backlog)

Ordenado por "barato primeiro, maior valor pro caso de uso (carro) depois".
Pegar o próximo item não marcado quando for continuar o projeto, a menos
que o usuário peça outra coisa.

### Fase 1 — baratas, qualidade de vida
- [ ] **Mensagens de erro amigáveis**: traduzir as exceções cruas do
  yt-dlp ("This video is unavailable" etc.) pra frases em português
  ("vídeo privado", "removido", "bloqueado na sua região") no log — hoje
  o usuário leigo ve a exceção do jeito que o yt-dlp devolve.
- [ ] **Limite de itens de playlist**: campo "baixar só os N primeiros/
  últimos N" — útil em playlist enorme quando só quer os recentes (hoje
  isso já dá pra fazer manualmente com "Mostrar lista pra escolher o que
  baixar", mas um campo direto evita ter que desmarcar um por um).
- [x] **Normalizar volume** — `NormalizarVolumePP` (`when="after_move"`),
  um passe de `ffmpeg` com `-af loudnorm=I=-16:TP=-1.5:LRA=11`, video em
  `-c:v copy` (sem perda, sem demora extra) e audio re-encodado em AAC
  192k. Checkbox "Normalizar volume", default ligado. Se o ffmpeg falhar
  nesse passo, mantem o arquivo original (log de aviso, nao derruba o
  item).
- [ ] **Drag-and-drop** de texto/`.txt` direto na caixa de links, além de
  colar/importar.
- [ ] **Validar extensão final** = `.mp4` sempre: se o merge do ffmpeg
  cair pra `.mkv`/`.webm` em algum caso raro, avisar no log em vez de
  deixar passar silenciosamente.

### Fase 2 — mais trabalho, valor alto
- [x] **Metadados no arquivo** (título/artista/data/link de origem) —
  via `postprocessors: [{"key": "FFmpegMetadata", ...}]` do yt-dlp,
  `add_chapters: False` e `add_infojson: "never"` pra não precisar de
  `ffprobe`. **Não inclui a capa/thumbnail**: `EmbedThumbnail` do yt-dlp
  exige `ffprobe`, que o `imageio-ffmpeg` não traz — testado e confirmado
  o erro (`ffprobe not found`) antes de descartar essa parte. Se algum dia
  quiser capa embutida, a saída é trocar `imageio-ffmpeg` por um pacote
  que traga os dois binários (ex. `static-ffmpeg`), o que muda
  `requirements.txt` e exige recriar o `.venv` do usuário — avaliar se
  vale, já que rádio de carro mostrando capa em arquivo de **vídeo** (não
  áudio) é incerto. `AjustarTituloPP` ganhou `preencher_artista` pra
  usar o canal como artista quando o vídeo não tem artista cadastrado
  (senão a tag fica vazia). Checkbox "Incluir título/artista/data como
  metadados", default ligado.
- [x] **Escolher quais vídeos baixar antes de começar**: checkbox
  "Mostrar lista pra escolher o que baixar antes de começar" (default
  desligado, pra não atrapalhar o caso comum de 1-2 links). Quando
  ligado, `_iniciar_download` manda pra `_coletar_e_revisar` em vez de
  `_baixar_tudo`; essa so faz a pre-varredura e abre `_abrir_selecao`
  (`Toplevel` com checklist scrollavel, todos marcados por padrão,
  "Marcar/Desmarcar todos", contador ao vivo). Confirmar sobe uma thread
  nova pra `_baixar_itens` so com os marcados; Cancelar (ou fechar a
  janela, ou clicar "Parar" na janela principal — ha um polling de
  `parar_flag` a cada 200ms enquanto a tela esta aberta) chama
  `_cancelar_revisao` e volta tudo ao estado pronto. `_baixar_tudo` foi
  dividido em `_coletar_itens` (ja existia) + `_baixar_itens` (o laço de
  download) pra os dois fluxos (com e sem revisão) reaproveitarem o mesmo
  código de download.
- [ ] **Checar espaço livre no pendrive** antes de começar, considerando
  a qualidade escolhida (estimativa), e avisar se a lista não vai caber.
- [ ] **Modo áudio (MP3)**: alternativa a baixar vídeo, pra quem só quer
  som tocando — reaproveita o `ffmpeg` já embutido. Com metadados e
  normalização de volume já implementados, esse modo ganha ainda mais
  valor (áudio puro é onde capa/tag realmente aparece no player).
- [ ] **Detectar/ejetar pendrive**: validar que o destino é mídia
  removível e oferecer ejeção segura ao final do download.

### Fase 3 — mais arriscadas/complexas
- [ ] **Dividir vídeo por capítulos**: vídeo de "álbum completo"/show com
  marcação de capítulo por faixa vira 1 arquivo só hoje; yt-dlp consegue
  splitar automaticamente. Mexe em como a numeração do nome de arquivo
  funciona (um "item" vira N arquivos) — avaliar junto com o padrão de
  nome atual antes de implementar.
- [ ] **Download paralelo (2-3 por vez)**: ganho real de throughput, mas
  exige repensar a UI de progresso/log (hoje é 1 vídeo por vez, sequencial
  e simples de acompanhar) — avaliar se vale a complexidade pro público
  alvo (leigo).
- [ ] **Retomar download interrompido** (pendrive ejetado no meio, queda
  de internet) sem recomeçar a lista inteira.

Ao fechar um item desta lista, marcar `[x]` aqui e atualizar o `README.md`
com a seção correspondente (ver `README.md` atual como modelo de tom:
direto, sem jargão técnico, sempre com um exemplo do nome de arquivo ou
do texto que aparece no log).

## Checklist pra adicionar uma feature nova

1. Função pura (sem UI) primeiro, se a lógica permitir — mais fácil de
   testar isolada via `python -c`.
2. Se precisa de opção configurável: `BooleanVar`/`StringVar` no
   `__init__`, widget em `_montar_layout`, entrada no dict `opcoes` em
   `_iniciar_download`, e inclusão em `_carregar_preferencias`/
   `_salvar_preferencias`.
3. Testar com download real (vídeo curto público) antes de considerar
   pronto — a maioria dos bugs reais desse projeto até agora só apareceu
   rodando de verdade contra o yt-dlp (ex.: o bug do `trim_file_name`).
4. Atualizar `README.md` (usuário final) e, se mudou decisão de
   arquitetura/gotcha, este `CLAUDE.md`.
5. Marcar o item correspondente no backlog acima, se for o caso.
