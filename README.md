# Baixador de Videos do YouTube (MP4 para o carro)

Programa simples com janela para baixar uma lista de videos do YouTube em MP4
e salvar direto no pendrive, prontos para tocar no som/multimidia do carro.

## Como usar

1. Conecte o pendrive no computador.
2. De dois cliques em **"Abrir Downloader.bat"**.
3. Cole os links do YouTube na caixa de texto, um por linha (ou clique em
   "Carregar links de um arquivo .txt" para importar de um arquivo).
4. Clique em **"Selecionar..."** e escolha a pasta/pendrive onde os videos
   devem ser salvos.
5. Escolha a qualidade (720p e um bom equilibrio entre qualidade e tamanho
   do arquivo para tocar no radio do carro).
6. Escolha o padrao do nome dos arquivos (veja abaixo).
7. Clique em **"Baixar lista"** e aguarde. Antes de baixar, o programa
   analisa os links e mostra no log o que encontrou (video solto ou
   playlist, com a quantidade de videos). Depois o log mostra o progresso
   de cada video.

Os videos sao salvos em MP4 (video H.264 + audio AAC), que e o formato mais
aceito pelos radios/multimidia automotivos.

## Playlists

O programa identifica sozinho quando o link e de uma playlist (ou de um link
de video que tambem tem `&list=`) e registra no log, por exemplo:

```
Playlist identificada: "Rock Classico" - 42 video(s).
```

A playlist e expandida em videos antes do download, entao a barra de
progresso conta videos (nao links) e o botao **Parar** interrompe entre um
video e outro.

Duas opcoes controlam esse comportamento:

- **"Baixar a playlist inteira quando o link tiver playlist"** - se
  desmarcar, um link de video que tenha playlist junto baixa so aquele
  video.
- **"Criar uma subpasta para cada playlist"** - cada playlist vira uma
  pasta dentro do destino, com o nome da playlist.
- **"Mostrar lista pra escolher o que baixar antes de comecar"** - em vez
  de baixar tudo direto, abre uma tela com um checkbox pra cada video
  encontrado (todos marcados por padrao). Da pra desmarcar os que nao
  quer, usar "Marcar todos"/"Desmarcar todos", e so entao clicar em
  "Baixar selecionados". Util em playlist grande quando so quer parte dos
  videos. "Cancelar" (ou o botao "Parar" da janela principal) fecha a
  tela sem baixar nada.

## Nome dos arquivos

No quadro **"Nome dos arquivos"** da para escolher o padrao; a janela mostra
um exemplo do resultado enquanto voce escolhe:

| Padrao | Resultado |
| --- | --- |
| `Titulo` | `Tempo Perdido.mp4` |
| `Numero - Titulo` | `01 - Tempo Perdido.mp4` |
| `Canal - Titulo` | `Legiao Urbana - Tempo Perdido.mp4` |
| `Numero - Canal - Titulo` | `01 - Legiao Urbana - Tempo Perdido.mp4` |
| `Artista - Musica` | `Legiao Urbana - Tempo Perdido.mp4` |
| `Titulo [id do video]` | `Tempo Perdido [abc123].mp4` |

O **Numero** e a posicao do video na playlist (com zeros a esquerda, para a
ordem ficar certa no radio do carro); para links soltos, e a ordem em que
voce colou. O padrao `Artista - Musica` usa os dados de musica do YouTube
quando existem e cai para canal/titulo quando nao existem.

Mais duas opcoes:

- **"Nomes simples"** - tira acentos e caracteres especiais e troca espacos
  por `_` (`01_-_Tempo_Perdido.mp4`). Deixe marcada se o radio nao aceitar
  acentos.
- **"Limpar titulos"** - remove os sufixos de propaganda do YouTube, como
  `(Official Music Video)`, `[Clipe Oficial]`, `(HD)`, `| Lyrics`. Titulos
  que usam essas palavras de verdade (ex.: "Tutorial de HD externo") nao sao
  alterados, e o titulo nunca fica vazio.

O titulo e limitado a 80 caracteres dentro do nome do arquivo, para nao
estourar o limite de caminho do Windows/pendrive.

## Audio e metadados

No quadro **"Audio e metadados"**:

- **"Normalizar volume"** - deixa o volume mais parecido entre os videos
  baixados, pra nao precisar ficar ajustando o som do radio a cada faixa.
  Faz isso regravando so o audio (o video continua copiado, sem perda e
  sem demorar mais por causa disso). Como regrava o audio, use com cautela
  se quiser preservar a faixa de audio 100% identica ao original.
- **"Incluir titulo/artista/data como metadados no arquivo"** - grava
  titulo, artista/canal, data de publicacao e o link de origem dentro do
  proprio arquivo (nao so no nome). Alguns radios/multimidia mostram essas
  informacoes na tela de "tocando agora" - outros so leem o nome do
  arquivo mesmo, entao o efeito depende do aparelho. Nao inclui a capa
  (imagem de thumbnail) do video: isso exigiria uma ferramenta extra
  (`ffprobe`) que o programa nao usa hoje.

## Duplicados e repeticoes

No quadro **"Duplicados e repeticoes"**:

- **"Ignorar links repetidos na lista colada"** - se voce colar o mesmo
  video mais de uma vez (ou ele aparecer solto e tambem dentro de uma
  playlist colada), so a primeira ocorrencia e baixada. O log mostra
  quantos foram ignorados.
- **"Pular videos ja baixados antes"** - o programa guarda um arquivo de
  controle (`.downloader_historico.txt`) na pasta de destino com os videos
  ja baixados por ali. Rodando a mesma lista de novo (por exemplo, toda vez
  que o pendrive e atualizado), quem ja esta la nao e baixado de novo, mesmo
  que o padrao do nome do arquivo tenha mudado nesse meio tempo. Desmarque
  essa opcao se quiser forcar o download de novo de tudo (substitui o
  arquivo existente).

## Preferencias

As escolhas feitas na janela (pasta de destino, qualidade, padrao de nome,
opcoes marcadas) sao salvas automaticamente em `config.json`, ao lado do
programa, e recarregadas na proxima vez que ele abrir. Pode apagar esse
arquivo a qualquer momento para voltar as opcoes padrao.

## Log

- **"Limpar log"** - apaga o texto do log na tela (nao afeta os downloads).
- **"Copiar links que falharam"** - fica habilitado quando algum link nao
  pode ser baixado (video indisponivel, erro de rede etc.) e copia esses
  links para a area de transferencia, prontos para colar de novo e tentar
  outra vez.

## Observacoes

- Baixe apenas videos que voce tem direito de baixar (uso pessoal, videos
  proprios, licenciados ou de dominio publico). Respeite os Termos de Uso do
  YouTube e direitos autorais.
- Se um video falhar (privado, removido, etc.), o programa continua com os
  proximos e mostra o erro no log ao final; use "Copiar links que falharam"
  para tentar so esses de novo.

## Primeira instalacao (ja feita para voce)

Foi criado um ambiente virtual Python em `.venv` com as dependencias:

- `yt-dlp` - motor de download dos videos do YouTube
- `imageio-ffmpeg` - fornece o `ffmpeg` (necessario para juntar video+audio
  em MP4), sem precisar instalar nada separado no Windows

Se precisar reinstalar do zero:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Atualizar o yt-dlp

O YouTube muda com frequencia. Se os downloads pararem de funcionar, atualize
o yt-dlp:

```powershell
.\.venv\Scripts\pip install --upgrade yt-dlp
```
