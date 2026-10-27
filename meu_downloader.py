"""
Baixador de videos do YouTube para MP4, pensado para uso no som/multimidia do carro.

Cole uma lista de links (um por linha), escolha a pasta de destino (pendrive)
e clique em Baixar. Os arquivos sao salvos em MP4 (H.264 + AAC), formato
compativel com a grande maioria dos radios/multimidia automotivos.

O programa identifica automaticamente quando um link e de playlist: mostra
quantos videos ela tem, pode criar uma subpasta por playlist e numera os
arquivos na ordem da playlist.
"""

import json
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import imageio_ffmpeg
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import sanitize_filename

QUALIDADES = {
    "480p (mais compativel / arquivo menor)": 480,
    "720p (recomendado)": 720,
    "1080p (Full HD)": 1080,
    "Melhor disponivel": None,
}

# {n} vira o numero do video (na playlist ou na ordem da lista colada).
PADROES_NOME = {
    "Titulo": "%(title)s",
    "Numero - Titulo": "{n} - %(title)s",
    "Canal - Titulo": "%(uploader)s - %(title)s",
    "Numero - Canal - Titulo": "{n} - %(uploader)s - %(title)s",
    "Artista - Musica (usa Canal/Titulo se faltar)": "%(artist,uploader)s - %(track,title)s",
    "Titulo [id do video]": "%(title)s [%(id)s]",
}
PADRAO_PADRAO = "Numero - Titulo"

# Preferencias (pasta, qualidade, padrao de nome etc.) ficam salvas ao lado
# do programa e sao recarregadas na proxima vez que ele abrir.
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Guarda os IDs dos videos ja baixados em cada pasta de destino, para a
# opcao "Pular videos ja baixados antes" funcionar mesmo que o padrao de
# nome do arquivo mude entre uma execucao e outra.
ARQUIVO_HISTORICO = ".downloader_historico.txt"

# Trechos de "ruido" comuns em titulos do YouTube, removidos quando a opcao
# "Limpar titulos" esta marcada.
_PALAVRAS_LIXO = (
    r"official\s*(music\s*)?(video|audio|lyric\s*video|visualizer)|"
    r"video\s*oficial|audio\s*oficial|clipe\s*oficial|musica\s*oficial|"
    r"lyric[s]?|letra|legendado|official|oficial|"
    r"hd|hq|full\s*hd|4k|1080p|720p|remaster(ed)?(\s*\d{4})?"
)
_REGEX_LIXO = [
    # (Official Video), [Clipe Oficial], (HD) etc.
    re.compile(r"\s*[\(\[]\s*(?:%s)[^)\]]*[\)\]]" % _PALAVRAS_LIXO, re.IGNORECASE),
    # " - Official Video" / " | Clipe Oficial" no fim do titulo
    re.compile(r"\s*[-|–]\s*(?:%s)[^-|–]*$" % _PALAVRAS_LIXO, re.IGNORECASE),
]
_REGEX_ESPACOS = re.compile(r"\s{2,}")


def limpar_titulo(titulo):
    """Remove sufixos tipo '(Official Video)' sem nunca devolver nome vazio."""
    limpo = titulo
    for regex in _REGEX_LIXO:
        limpo = regex.sub("", limpo)
    limpo = _REGEX_ESPACOS.sub(" ", limpo).strip(" -|–_.")
    return limpo or titulo


# Limite de caracteres do titulo dentro do nome do arquivo. Nao usamos a
# opcao trim_file_name do yt-dlp porque ela corta o caminho inteiro (e nao
# so o nome), o que joga o arquivo para fora da pasta de destino.
LIMITE_TITULO = 80


class AjustarTituloPP(PostProcessor):
    """Limpa e encurta o titulo antes do nome do arquivo ser montado."""

    def __init__(self, limpar=True, limite=LIMITE_TITULO, preencher_artista=False, downloader=None):
        super().__init__(downloader)
        self.limpar = limpar
        self.limite = limite
        self.preencher_artista = preencher_artista

    def run(self, info):
        titulo = info.get("title")
        if titulo:
            if self.limpar:
                titulo = limpar_titulo(titulo)
            if len(titulo) > self.limite:
                titulo = titulo[: self.limite].rstrip(" -|_.")
            info["title"] = titulo or info["title"]
        if self.preencher_artista and not info.get("artist"):
            # Sem isso, o metadado "artista" do arquivo fica vazio quando o
            # video nao tem artista cadastrado (caso comum fora de clipes
            # oficiais de musica).
            info["artist"] = info.get("uploader")
        return [], info


# Normalizacao de volume: um unico passo de ffmpeg com o filtro "loudnorm",
# reaproveitando o video (copy, sem perda/sem gastar tempo) e regravando so
# o audio. Roda depois que o arquivo final ja esta na pasta de destino.
PARAMETROS_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


class NormalizarVolumePP(PostProcessor):
    """Deixa o volume mais parecido entre os videos, bom pra tocar no carro."""

    def __init__(self, ffmpeg_path, log_fn=None, downloader=None):
        super().__init__(downloader)
        self.ffmpeg_path = ffmpeg_path
        self.log_fn = log_fn or (lambda msg: None)

    def run(self, info):
        caminho = info.get("filepath")
        if not caminho or not os.path.exists(caminho):
            return [], info

        temp = caminho + ".norm.mp4"
        comando = [
            self.ffmpeg_path,
            "-y",
            "-i",
            caminho,
            "-c:v",
            "copy",
            "-af",
            PARAMETROS_LOUDNORM,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            temp,
        ]
        try:
            subprocess.run(
                comando,
                check=True,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            os.replace(temp, caminho)
        except Exception as e:
            self.log_fn(f"Nao consegui normalizar o volume (arquivo original mantido): {e}")
            if os.path.exists(temp):
                try:
                    os.remove(temp)
                except OSError:
                    pass
        return [], info


def montar_formato(altura_max):
    if altura_max is None:
        filtro = ""
    else:
        filtro = f"[height<={altura_max}]"
    # Prioriza video H.264 (avc1) + audio AAC (m4a), que e o combo mais
    # aceito pelos radios de carro. Cai para o melhor mp4 disponivel se
    # nao houver essa combinacao, e por ultimo para o melhor formato geral.
    return (
        f"bestvideo{filtro}[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
        f"best{filtro}[ext=mp4]/"
        f"best{filtro}/best"
    )


def montar_outtmpl(destino, subpasta, padrao, numero, largura, simples=False):
    """Monta o template de saida do yt-dlp para um video especifico."""
    pasta = os.path.join(destino, subpasta) if subpasta else destino
    # No template do yt-dlp, '%' literal precisa virar '%%'.
    pasta_escapada = pasta.replace("%", "%%")
    nome = padrao.replace("{n}", str(numero).zfill(largura))
    if simples:
        # Os campos (%(title)s etc.) ja saem sem espaco; aqui tiramos os
        # espacos dos separadores para o nome inteiro ficar uniforme.
        nome = nome.replace(" ", "_")
    return os.path.join(pasta_escapada, nome + ".%(ext)s")


_EXEMPLO_CAMPOS = [
    ("%(artist,uploader)s", "Artista"),
    ("%(track,title)s", "Musica"),
    ("%(uploader)s", "Canal"),
    ("%(title)s", "Nome do Video (Official Video)"),
    ("%(id)s", "dQw4w9WgXcQ"),
]


def exemplo_nome(padrao, limpar, simples):
    """Exemplo de como o arquivo vai se chamar, para mostrar na janela."""
    nome = padrao.replace("{n}", "01")
    if simples:
        nome = nome.replace(" ", "_")
    for token, valor in _EXEMPLO_CAMPOS:
        if limpar:
            valor = limpar_titulo(valor)
        nome = nome.replace(token, sanitize_filename(valor, restricted=simples))
    return nome + ".mp4"


def carregar_config():
    """Le as preferencias salvas da ultima vez. Nunca falha: pior caso, {}."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def salvar_config(dados):
    """Grava as preferencias atuais. Falha silenciosa (nao e critico)."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def carregar_historico(destino):
    """IDs de videos ja baixados nessa pasta em execucoes anteriores."""
    caminho = os.path.join(destino, ARQUIVO_HISTORICO)
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return {linha.strip() for linha in f if linha.strip()}
    except OSError:
        return set()


def registrar_historico(destino, video_id):
    caminho = os.path.join(destino, ARQUIVO_HISTORICO)
    try:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(video_id + "\n")
    except OSError:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("Baixador de Videos do YouTube (MP4 para o carro)")
        root.geometry("780x900")
        root.minsize(680, 600)

        self.fila_mensagens = queue.Queue()
        self.pasta_destino = tk.StringVar(value="")
        self.qualidade = tk.StringVar(value="720p (recomendado)")
        self.padrao_nome = tk.StringVar(value=PADRAO_PADRAO)
        self.nomes_simples = tk.BooleanVar(value=True)
        self.limpar_titulos = tk.BooleanVar(value=True)
        self.baixar_playlists = tk.BooleanVar(value=True)
        self.subpasta_playlist = tk.BooleanVar(value=True)
        self.ignorar_repetidos = tk.BooleanVar(value=True)
        self.pular_duplicados = tk.BooleanVar(value=True)
        self.incluir_metadados = tk.BooleanVar(value=True)
        self.normalizar_volume = tk.BooleanVar(value=True)
        self.revisar_antes = tk.BooleanVar(value=False)
        self.texto_exemplo = tk.StringVar(value="")
        self.parar_flag = threading.Event()
        self.baixando = False
        self.urls_falhas = []

        self._montar_layout()
        self._carregar_preferencias()
        self._atualizar_exemplo()
        self.root.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.root.after(150, self._processar_fila)

    def _montar_layout(self):
        pad = {"padx": 10, "pady": 6}

        lbl = tk.Label(self.root, text="Cole aqui os links do YouTube (um por linha):")
        lbl.pack(anchor="w", **pad)

        self.txt_links = scrolledtext.ScrolledText(self.root, height=6, wrap="word")
        self.txt_links.pack(fill="both", expand=False, padx=10)

        frame_arquivo = tk.Frame(self.root)
        frame_arquivo.pack(fill="x", **pad)
        tk.Button(
            frame_arquivo, text="Carregar links de um arquivo .txt", command=self._carregar_txt
        ).pack(side="left")

        # Pasta de destino (pendrive)
        frame_destino = tk.Frame(self.root)
        frame_destino.pack(fill="x", **pad)
        tk.Label(frame_destino, text="Pasta de destino (pendrive):").pack(side="left")
        self.entry_destino = tk.Entry(frame_destino, textvariable=self.pasta_destino)
        self.entry_destino.pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(frame_destino, text="Selecionar...", command=self._selecionar_pasta).pack(
            side="left"
        )

        # Qualidade
        frame_qualidade = tk.Frame(self.root)
        frame_qualidade.pack(fill="x", **pad)
        tk.Label(frame_qualidade, text="Qualidade do video:").pack(side="left")
        ttk.Combobox(
            frame_qualidade,
            textvariable=self.qualidade,
            values=list(QUALIDADES.keys()),
            state="readonly",
            width=35,
        ).pack(side="left", padx=8)

        # Nome dos arquivos
        frame_nomes = tk.LabelFrame(self.root, text="Nome dos arquivos")
        frame_nomes.pack(fill="x", **pad)

        linha_padrao = tk.Frame(frame_nomes)
        linha_padrao.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(linha_padrao, text="Padrao:").pack(side="left")
        combo_padrao = ttk.Combobox(
            linha_padrao,
            textvariable=self.padrao_nome,
            values=list(PADROES_NOME.keys()),
            state="readonly",
            width=42,
        )
        combo_padrao.pack(side="left", padx=8)
        combo_padrao.bind("<<ComboboxSelected>>", lambda _e: self._atualizar_exemplo())

        linha_opcoes = tk.Frame(frame_nomes)
        linha_opcoes.pack(fill="x", padx=8)
        tk.Checkbutton(
            linha_opcoes,
            text="Nomes simples (sem acento/espaco)",
            variable=self.nomes_simples,
            command=self._atualizar_exemplo,
        ).pack(side="left")
        tk.Checkbutton(
            linha_opcoes,
            text="Limpar titulos (tira Official Video, HD, Lyrics...)",
            variable=self.limpar_titulos,
            command=self._atualizar_exemplo,
        ).pack(side="left", padx=12)

        tk.Label(frame_nomes, textvariable=self.texto_exemplo, anchor="w", fg="#555555").pack(
            fill="x", padx=8, pady=(2, 8)
        )

        # Playlists
        frame_playlist = tk.LabelFrame(self.root, text="Playlists")
        frame_playlist.pack(fill="x", **pad)
        tk.Checkbutton(
            frame_playlist,
            text="Baixar a playlist inteira quando o link tiver playlist",
            variable=self.baixar_playlists,
        ).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Checkbutton(
            frame_playlist,
            text="Criar uma subpasta para cada playlist",
            variable=self.subpasta_playlist,
        ).pack(anchor="w", padx=8, pady=(0, 2))
        tk.Checkbutton(
            frame_playlist,
            text="Mostrar lista pra escolher o que baixar antes de comecar",
            variable=self.revisar_antes,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        # Audio e metadados
        frame_audio = tk.LabelFrame(self.root, text="Audio e metadados")
        frame_audio.pack(fill="x", **pad)
        tk.Checkbutton(
            frame_audio,
            text="Normalizar volume (deixa os videos com volume parecido entre si)",
            variable=self.normalizar_volume,
        ).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Checkbutton(
            frame_audio,
            text="Incluir titulo/artista/data como metadados no arquivo",
            variable=self.incluir_metadados,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        # Duplicados e repeticoes
        frame_dup = tk.LabelFrame(self.root, text="Duplicados e repeticoes")
        frame_dup.pack(fill="x", **pad)
        tk.Checkbutton(
            frame_dup,
            text="Ignorar links repetidos na lista colada",
            variable=self.ignorar_repetidos,
        ).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Checkbutton(
            frame_dup,
            text="Pular videos ja baixados antes (usa um arquivo de controle na pasta de destino)",
            variable=self.pular_duplicados,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        # Botoes de acao
        frame_acoes = tk.Frame(self.root)
        frame_acoes.pack(fill="x", **pad)
        self.btn_baixar = tk.Button(
            frame_acoes,
            text="Baixar lista",
            command=self._iniciar_download,
            bg="#2e7d32",
            fg="white",
        )
        self.btn_baixar.pack(side="left")
        self.btn_parar = tk.Button(
            frame_acoes, text="Parar", command=self._parar, state="disabled"
        )
        self.btn_parar.pack(side="left", padx=8)

        # Progresso
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 6))

        self.lbl_status = tk.Label(self.root, text="Pronto.", anchor="w")
        self.lbl_status.pack(fill="x", padx=10)

        frame_log_topo = tk.Frame(self.root)
        frame_log_topo.pack(fill="x", padx=10)
        tk.Label(frame_log_topo, text="Log:").pack(side="left")
        tk.Button(frame_log_topo, text="Limpar log", command=self._limpar_log).pack(
            side="right"
        )
        self.btn_copiar_falhas = tk.Button(
            frame_log_topo,
            text="Copiar links que falharam",
            command=self._copiar_falhas,
            state="disabled",
        )
        self.btn_copiar_falhas.pack(side="right", padx=8)

        self.txt_log = scrolledtext.ScrolledText(self.root, height=7, state="disabled")
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _atualizar_exemplo(self):
        exemplo = exemplo_nome(
            PADROES_NOME[self.padrao_nome.get()],
            self.limpar_titulos.get(),
            self.nomes_simples.get(),
        )
        self.texto_exemplo.set(f"Exemplo: {exemplo}")

    # ------------------------------------------------------------------
    # Preferencias (salvas em config.json ao lado do programa)
    # ------------------------------------------------------------------

    def _carregar_preferencias(self):
        dados = carregar_config()
        if not dados:
            return
        if dados.get("pasta_destino"):
            self.pasta_destino.set(dados["pasta_destino"])
        if dados.get("qualidade") in QUALIDADES:
            self.qualidade.set(dados["qualidade"])
        if dados.get("padrao_nome") in PADROES_NOME:
            self.padrao_nome.set(dados["padrao_nome"])
        for chave, var in (
            ("nomes_simples", self.nomes_simples),
            ("limpar_titulos", self.limpar_titulos),
            ("baixar_playlists", self.baixar_playlists),
            ("subpasta_playlist", self.subpasta_playlist),
            ("ignorar_repetidos", self.ignorar_repetidos),
            ("pular_duplicados", self.pular_duplicados),
            ("incluir_metadados", self.incluir_metadados),
            ("normalizar_volume", self.normalizar_volume),
            ("revisar_antes", self.revisar_antes),
        ):
            if chave in dados:
                var.set(bool(dados[chave]))

    def _salvar_preferencias(self):
        salvar_config(
            {
                "pasta_destino": self.pasta_destino.get().strip(),
                "qualidade": self.qualidade.get(),
                "padrao_nome": self.padrao_nome.get(),
                "nomes_simples": self.nomes_simples.get(),
                "limpar_titulos": self.limpar_titulos.get(),
                "baixar_playlists": self.baixar_playlists.get(),
                "subpasta_playlist": self.subpasta_playlist.get(),
                "ignorar_repetidos": self.ignorar_repetidos.get(),
                "pular_duplicados": self.pular_duplicados.get(),
                "incluir_metadados": self.incluir_metadados.get(),
                "normalizar_volume": self.normalizar_volume.get(),
                "revisar_antes": self.revisar_antes.get(),
            }
        )

    def _ao_fechar(self):
        self._salvar_preferencias()
        self.root.destroy()

    def _limpar_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _copiar_falhas(self):
        if not self.urls_falhas:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(self.urls_falhas))
        self.lbl_status.configure(
            text=f"{len(self.urls_falhas)} link(s) com falha copiados para a area de transferencia."
        )

    def _carregar_txt(self):
        caminho = filedialog.askopenfilename(
            title="Selecionar arquivo de links", filetypes=[("Arquivo de texto", "*.txt")]
        )
        if not caminho:
            return
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()
        ja_tem = self.txt_links.get("1.0", "end").strip()
        self.txt_links.insert("end", ("\n" if ja_tem else "") + conteudo)

    def _selecionar_pasta(self):
        caminho = filedialog.askdirectory(title="Selecionar pasta do pendrive")
        if caminho:
            self.pasta_destino.set(caminho)

    def _log(self, msg):
        self.fila_mensagens.put(("log", msg))

    def _processar_fila(self):
        try:
            while True:
                tipo, valor = self.fila_mensagens.get_nowait()
                if tipo == "log":
                    self.txt_log.configure(state="normal")
                    self.txt_log.insert("end", valor + "\n")
                    self.txt_log.see("end")
                    self.txt_log.configure(state="disabled")
                elif tipo == "status":
                    self.lbl_status.configure(text=valor)
                elif tipo == "progress_max":
                    self.progress.configure(maximum=max(valor, 1), value=0)
                elif tipo == "progress_step":
                    self.progress.step(1)
                elif tipo == "falhas":
                    self.urls_falhas = valor
                    self.btn_copiar_falhas.configure(
                        state="normal" if valor else "disabled"
                    )
                elif tipo == "revisar":
                    itens, falhas_leitura, destino, opcoes = valor
                    self._abrir_selecao(itens, falhas_leitura, destino, opcoes)
                elif tipo == "fim":
                    self._finalizar_ui(valor)
        except queue.Empty:
            pass
        self.root.after(150, self._processar_fila)

    def _pegar_links(self):
        bruto = self.txt_links.get("1.0", "end")
        links = [linha.strip() for linha in bruto.splitlines() if linha.strip()]
        return links

    def _iniciar_download(self):
        if self.baixando:
            return

        links = self._pegar_links()
        if not links:
            messagebox.showwarning("Sem links", "Cole ao menos um link do YouTube.")
            return

        destino = self.pasta_destino.get().strip()
        if not destino:
            messagebox.showwarning("Sem pasta", "Selecione a pasta do pendrive antes de baixar.")
            return
        if not os.path.isdir(destino):
            try:
                os.makedirs(destino, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Pasta invalida", f"Nao foi possivel usar essa pasta:\n{e}")
                return

        self._salvar_preferencias()

        self.parar_flag.clear()
        self.baixando = True
        self.btn_baixar.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.urls_falhas = []
        self.btn_copiar_falhas.configure(state="disabled")
        self.fila_mensagens.put(("progress_max", len(links)))
        self.fila_mensagens.put(("status", "Analisando os links..."))

        opcoes = {
            "altura_max": QUALIDADES[self.qualidade.get()],
            "padrao": PADROES_NOME[self.padrao_nome.get()],
            "restrict_names": self.nomes_simples.get(),
            "limpar": self.limpar_titulos.get(),
            "baixar_playlists": self.baixar_playlists.get(),
            "subpasta": self.subpasta_playlist.get(),
            "ignorar_repetidos": self.ignorar_repetidos.get(),
            "pular_duplicados": self.pular_duplicados.get(),
            "incluir_metadados": self.incluir_metadados.get(),
            "normalizar_volume": self.normalizar_volume.get(),
        }

        alvo = self._coletar_e_revisar if self.revisar_antes.get() else self._baixar_tudo
        thread = threading.Thread(target=alvo, args=(links, destino, opcoes), daemon=True)
        thread.start()

    def _parar(self):
        self.parar_flag.set()
        self._log("Parando apos o download atual terminar...")

    # ------------------------------------------------------------------
    # Analise dos links (identifica playlists)
    # ------------------------------------------------------------------

    def _coletar_itens(self, links, baixar_playlists, ignorar_repetidos=True):
        """Expande os links em uma lista de videos, identificando playlists."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
            "noplaylist": not baixar_playlists,
        }
        de_playlists = []
        avulsos = []
        falhas_leitura = []

        with YoutubeDL(opts) as ydl:
            for link in links:
                if self.parar_flag.is_set():
                    break
                try:
                    info = ydl.extract_info(link, download=False)
                except Exception as e:
                    self._log(f"Nao consegui ler o link {link}: {e}")
                    falhas_leitura.append(link)
                    continue
                if not info:
                    self._log(f"Nao consegui ler o link {link} (indisponivel?).")
                    falhas_leitura.append(link)
                    continue

                if info.get("_type") == "playlist":
                    entradas = self._achatar_entradas(info)
                    if not entradas:
                        self._log(f"Playlist vazia ou indisponivel: {link}")
                        falhas_leitura.append(link)
                        continue
                    nome_playlist = info.get("title") or "Playlist"
                    self._log(
                        f'Playlist identificada: "{nome_playlist}" - {len(entradas)} video(s).'
                    )
                    largura = max(2, len(str(len(entradas))))
                    for numero, entrada in enumerate(entradas, start=1):
                        url = self._url_da_entrada(entrada)
                        de_playlists.append(
                            {
                                "url": url,
                                "id": entrada.get("id"),
                                "titulo": entrada.get("title") or url or "(sem titulo)",
                                "playlist": nome_playlist,
                                "numero": numero,
                                "largura": largura,
                            }
                        )
                else:
                    titulo = info.get("title") or link
                    self._log(f"Video identificado: {titulo}")
                    avulsos.append(
                        {
                            "url": info.get("webpage_url") or link,
                            "id": info.get("id"),
                            "titulo": titulo,
                            "playlist": None,
                            "numero": len(avulsos) + 1,
                            "largura": 2,
                        }
                    )

        largura_avulsos = max(2, len(str(len(avulsos))))
        for item in avulsos:
            item["largura"] = largura_avulsos
        itens = de_playlists + avulsos

        if ignorar_repetidos:
            itens, repetidos = self._remover_repetidos(itens)
            if repetidos:
                self._log(f"Ignorados {repetidos} link(s) repetido(s) na lista.")

        return itens, falhas_leitura

    @staticmethod
    def _remover_repetidos(itens):
        """Remove videos repetidos (mesmo ID), mantendo a primeira ocorrencia."""
        vistos = set()
        resultado = []
        repetidos = 0
        for item in itens:
            chave = item.get("id") or item.get("url")
            if chave and chave in vistos:
                repetidos += 1
                continue
            if chave:
                vistos.add(chave)
            resultado.append(item)
        return resultado, repetidos

    def _achatar_entradas(self, info, profundidade=0):
        """Playlist de playlists (ex.: pagina de canal) vira uma lista unica."""
        entradas = []
        for entrada in info.get("entries") or []:
            if not entrada:
                continue
            if entrada.get("_type") == "playlist" and profundidade < 2:
                entradas.extend(self._achatar_entradas(entrada, profundidade + 1))
            else:
                entradas.append(entrada)
        return entradas

    @staticmethod
    def _url_da_entrada(entrada):
        url = entrada.get("url") or entrada.get("webpage_url")
        if not url and entrada.get("id"):
            url = entrada["id"]
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        return url

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _baixar_tudo(self, links, destino, opcoes):
        """Fluxo padrao: analisa os links e ja baixa tudo, sem revisao."""
        itens, falhas_leitura = self._coletar_itens(
            links, opcoes["baixar_playlists"], opcoes["ignorar_repetidos"]
        )
        if not itens:
            self._finalizar_sem_itens(falhas_leitura)
            return
        self._baixar_itens(itens, falhas_leitura, destino, opcoes)

    def _coletar_e_revisar(self, links, destino, opcoes):
        """Fluxo com revisao: analisa os links e abre a tela de selecao."""
        itens, falhas_leitura = self._coletar_itens(
            links, opcoes["baixar_playlists"], opcoes["ignorar_repetidos"]
        )
        if not itens:
            self._finalizar_sem_itens(falhas_leitura)
            return
        if falhas_leitura:
            self.fila_mensagens.put(("falhas", list(falhas_leitura)))
        self.fila_mensagens.put(("revisar", (itens, falhas_leitura, destino, opcoes)))

    def _finalizar_sem_itens(self, falhas_leitura):
        resumo = "Nenhum video encontrado nos links informados."
        if falhas_leitura:
            resumo += f" {len(falhas_leitura)} link(s) nao puderam ser lidos."
        self._log(resumo)
        self.fila_mensagens.put(("falhas", falhas_leitura))
        self.fila_mensagens.put(("fim", resumo))

    def _baixar_itens(self, itens, falhas_leitura, destino, opcoes):
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

        total = len(itens)
        self.fila_mensagens.put(("progress_max", total))
        self._log(f"Total a baixar: {total} video(s).")

        historico = carregar_historico(destino) if opcoes["pular_duplicados"] else set()

        sucesso = 0
        pulados = 0
        falhas = list(falhas_leitura)
        falhas_urls = list(falhas_leitura)

        for i, item in enumerate(itens, start=1):
            if self.parar_flag.is_set():
                self._log("Interrompido pelo usuario.")
                break

            rotulo = item["titulo"]
            if item["playlist"]:
                rotulo = f"{item['playlist']} #{item['numero']} - {rotulo}"

            url = item["url"]
            if not url:
                falhas.append(rotulo)
                self._log(f"[{i}/{total}] Sem link utilizavel: {rotulo}")
                self.fila_mensagens.put(("progress_step", None))
                continue

            if opcoes["pular_duplicados"] and item.get("id") and item["id"] in historico:
                pulados += 1
                self._log(f"[{i}/{total}] Pulado (ja baixado antes): {rotulo}")
                self.fila_mensagens.put(("progress_step", None))
                continue

            subpasta = ""
            if item["playlist"] and opcoes["subpasta"]:
                subpasta = sanitize_filename(item["playlist"], restricted=opcoes["restrict_names"])

            outtmpl = montar_outtmpl(
                destino,
                subpasta,
                opcoes["padrao"],
                item["numero"],
                item["largura"],
                opcoes["restrict_names"],
            )

            self.fila_mensagens.put(("status", f"Baixando {i}/{total}: {rotulo}"))
            self._log(f"[{i}/{total}] Iniciando: {rotulo}")

            ydl_opts = {
                "format": montar_formato(opcoes["altura_max"]),
                "merge_output_format": "mp4",
                "outtmpl": outtmpl,
                "ffmpeg_location": ffmpeg_path,
                "restrictfilenames": opcoes["restrict_names"],
                "windowsfilenames": True,
                "noplaylist": True,
                "ignoreerrors": False,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "progress_hooks": [self._fazer_hook_progresso(rotulo)],
            }
            if not opcoes["pular_duplicados"]:
                # Sem controle de duplicados, forca regravar mesmo se o
                # arquivo ja existir (comportamento padrao do yt-dlp e pular).
                ydl_opts["overwrites"] = True
            if opcoes["incluir_metadados"]:
                # Sem writethumbnail/EmbedThumbnail: embutir a capa exige
                # ffprobe, que o imageio-ffmpeg nao traz. So os metadados de
                # texto (titulo, artista, data, link de origem) ja cobrem o
                # caso de uso (rotulo "tocando agora" em radios que leem tag).
                ydl_opts["postprocessors"] = [
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                        "add_chapters": False,
                        "add_infojson": "never",
                    }
                ]

            try:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.add_post_processor(
                        AjustarTituloPP(
                            limpar=opcoes["limpar"],
                            preencher_artista=opcoes["incluir_metadados"],
                        ),
                        when="pre_process",
                    )
                    if opcoes["normalizar_volume"]:
                        ydl.add_post_processor(
                            NormalizarVolumePP(ffmpeg_path, log_fn=self._log),
                            when="after_move",
                        )
                    ret = ydl.download([url])
                if ret == 0:
                    sucesso += 1
                    self._log(f"[{i}/{total}] Concluido: {rotulo}")
                    if opcoes["pular_duplicados"] and item.get("id"):
                        registrar_historico(destino, item["id"])
                        historico.add(item["id"])
                else:
                    falhas.append(rotulo)
                    falhas_urls.append(url)
                    self._log(f"[{i}/{total}] Falhou: {rotulo}")
            except Exception as e:
                falhas.append(rotulo)
                falhas_urls.append(url)
                self._log(f"[{i}/{total}] Erro em {rotulo}: {e}")

            self.fila_mensagens.put(("progress_step", None))

        resumo = f"Concluido: {sucesso}/{total} baixado(s)."
        if pulados:
            resumo += f" {pulados} ja estavam baixados."
        if falhas:
            resumo += f" Falharam {len(falhas)}: veja o log."
        self._log(resumo)
        self.fila_mensagens.put(("falhas", falhas_urls))
        self.fila_mensagens.put(("fim", resumo))

    def _fazer_hook_progresso(self, rotulo):
        def hook(d):
            if d.get("status") == "downloading":
                pct = d.get("_percent_str", "").strip()
                if pct:
                    self.fila_mensagens.put(("status", f"Baixando: {pct} - {rotulo}"))

        return hook

    def _finalizar_ui(self, resumo):
        self.baixando = False
        self.btn_baixar.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.lbl_status.configure(text=resumo)
        messagebox.showinfo("Downloads finalizados", resumo)

    # ------------------------------------------------------------------
    # Tela de revisao (escolher o que baixar antes de comecar)
    # ------------------------------------------------------------------

    def _abrir_selecao(self, itens, falhas_leitura, destino, opcoes):
        janela = tk.Toplevel(self.root)
        janela.title("Escolher o que baixar")
        janela.geometry("640x520")
        janela.minsize(480, 360)
        janela.transient(self.root)
        janela.grab_set()

        tk.Label(
            janela,
            text=f"{len(itens)} video(s) encontrado(s). Desmarque o que nao quer baixar:",
            anchor="w",
        ).pack(fill="x", padx=10, pady=(10, 4))

        frame_topo = tk.Frame(janela)
        frame_topo.pack(fill="x", padx=10)
        lbl_contagem = tk.Label(frame_topo, text="")
        lbl_contagem.pack(side="right")

        variaveis = []

        def atualizar_contagem():
            marcados = sum(1 for v in variaveis if v.get())
            lbl_contagem.configure(text=f"{marcados} de {len(itens)} selecionado(s)")

        def marcar_todos(valor):
            for v in variaveis:
                v.set(valor)
            atualizar_contagem()

        tk.Button(frame_topo, text="Marcar todos", command=lambda: marcar_todos(True)).pack(
            side="left"
        )
        tk.Button(
            frame_topo, text="Desmarcar todos", command=lambda: marcar_todos(False)
        ).pack(side="left", padx=6)

        frame_lista = tk.Frame(janela)
        frame_lista.pack(fill="both", expand=True, padx=10, pady=6)
        canvas = tk.Canvas(frame_lista, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=canvas.yview)
        frame_itens = tk.Frame(canvas)

        frame_itens.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        janela_canvas = canvas.create_window((0, 0), window=frame_itens, anchor="nw")
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfig(janela_canvas, width=e.width)
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for item in itens:
            rotulo = item["titulo"]
            if item["playlist"]:
                rotulo = f"{item['playlist']} #{item['numero']} - {rotulo}"
            var = tk.BooleanVar(value=True)
            variaveis.append(var)
            tk.Checkbutton(
                frame_itens, text=rotulo, variable=var, anchor="w", command=atualizar_contagem
            ).pack(fill="x", anchor="w")

        atualizar_contagem()

        def confirmar():
            selecionados = [item for item, v in zip(itens, variaveis) if v.get()]
            if not selecionados:
                messagebox.showwarning(
                    "Nada selecionado",
                    "Marque ao menos um video para baixar.",
                    parent=janela,
                )
                return
            janela.destroy()
            thread = threading.Thread(
                target=self._baixar_itens,
                args=(selecionados, falhas_leitura, destino, opcoes),
                daemon=True,
            )
            thread.start()

        def cancelar():
            janela.destroy()
            self._cancelar_revisao()

        frame_botoes = tk.Frame(janela)
        frame_botoes.pack(fill="x", padx=10, pady=10)
        tk.Button(
            frame_botoes,
            text="Baixar selecionados",
            command=confirmar,
            bg="#2e7d32",
            fg="white",
        ).pack(side="left")
        tk.Button(frame_botoes, text="Cancelar", command=cancelar).pack(side="left", padx=8)

        janela.protocol("WM_DELETE_WINDOW", cancelar)

        def verificar_parar():
            if not janela.winfo_exists():
                return
            if self.parar_flag.is_set():
                cancelar()
                return
            janela.after(200, verificar_parar)

        janela.after(200, verificar_parar)

    def _cancelar_revisao(self):
        self.baixando = False
        self.btn_baixar.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.lbl_status.configure(text="Cancelado pelo usuario.")
        self._log("Cancelado pelo usuario antes de baixar.")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
