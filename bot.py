"""Bot de Telegram para baixar vídeos do YouTube.

- Só vídeo, com escolha de qualidade via botões inline.
- Acesso restrito a uma allowlist de user IDs.
- Funciona com o Bot API oficial (limite 50 MB) ou com um Telegram Bot API
  server local (limite 2 GB) quando TELEGRAM_API_BASE_URL está definido.
"""

import asyncio
import base64
import logging
import os
import re
import uuid
from functools import wraps
from pathlib import Path

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("yt-bot")

# --------------------------------------------------------------------------- #
# Configuração via variáveis de ambiente
# --------------------------------------------------------------------------- #
TOKEN = os.environ["TELEGRAM_TOKEN"]
_raw_allowed = os.getenv("ALLOWED_USER_IDS", "").replace(" ", "")
# "*" libera o acesso para qualquer usuário.
ALLOW_ALL = "*" in _raw_allowed.split(",")
ALLOWED_USER_IDS = {
    int(x) for x in _raw_allowed.split(",") if x and x != "*"
}
MAX_HEIGHT = int(os.getenv("MAX_HEIGHT", "720"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/dl"))
API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL")  # ex.: http://telegram-bot-api:8081

# Limite efetivo de upload: 2 GB com server local, 50 MB no Bot API oficial.
MAX_FILESIZE = (2000 if API_BASE_URL else 50) * 1024 * 1024

# Qualidades oferecidas (filtradas pelo que o vídeo realmente tem e por MAX_HEIGHT).
QUALITY_CHOICES = [1080, 720, 480, 360]

YOUTUBE_RE = re.compile(
    r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)[\w\-]+",
    re.IGNORECASE,
)

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Cookies do YouTube (driblar o "confirm you're not a bot" em IPs de VPS).
# Pode ser via caminho de arquivo (COOKIES_FILE) ou via conteúdo base64 (YOUTUBE_COOKIES_B64).
COOKIES_FILE = os.getenv("COOKIES_FILE")
_cookies_b64 = os.getenv("YOUTUBE_COOKIES_B64")
if _cookies_b64 and not COOKIES_FILE:
    COOKIES_FILE = str(DOWNLOAD_DIR / "cookies.txt")
    Path(COOKIES_FILE).write_bytes(base64.b64decode(_cookies_b64))
    logger.info("Cookies carregados de YOUTUBE_COOKIES_B64")

# player_client alternativos (ex.: "android,ios,web"). Vazio = padrão do yt-dlp.
YT_PLAYER_CLIENT = os.getenv("YT_PLAYER_CLIENT", "").replace(" ", "")

# Proxy (IP residencial) para driblar o bloqueio do YouTube em IPs de datacenter.
# Ex.: http://usuario:senha@host:porta  ou  socks5://usuario:senha@host:porta
YT_PROXY = os.getenv("YT_PROXY", "").strip()

# Guarda a URL pendente por usuário entre o envio do link e a escolha da qualidade.
PENDING: dict[int, str] = {}


def _base_opts() -> dict:
    """Opções comuns do yt-dlp (cookies, anti-bot)."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE
    if YT_PROXY:
        opts["proxy"] = YT_PROXY
    if YT_PLAYER_CLIENT:
        opts["extractor_args"] = {
            "youtube": {"player_client": YT_PLAYER_CLIENT.split(",")}
        }
    return opts


def restricted(func):
    """Bloqueia qualquer usuário fora da allowlist."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not ALLOW_ALL and (not ALLOWED_USER_IDS or user.id not in ALLOWED_USER_IDS):
            logger.warning("Acesso negado para %s (%s)", user.id, user.username)
            if update.message:
                await update.message.reply_text(
                    f"⛔ Acesso negado. Seu ID é `{user.id}`.\n"
                    "Peça ao administrador para adicioná-lo à allowlist.",
                    parse_mode="Markdown",
                )
            elif update.callback_query:
                await update.callback_query.answer("⛔ Acesso negado.", show_alert=True)
            return
        return await func(update, context)

    return wrapper


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Manda um link do YouTube que eu baixo o vídeo pra você.\n"
        f"Limite de tamanho: {MAX_FILESIZE // (1024 * 1024)} MB."
    )


@restricted
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_match = YOUTUBE_RE.search(update.message.text or "")
    if not url_match:
        await update.message.reply_text("❌ Não reconheci um link do YouTube válido.")
        return

    url = url_match.group(0)
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        info = await asyncio.to_thread(_extract_info, url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao obter info")
        await update.message.reply_text(f"❌ Erro ao ler o vídeo: {exc}")
        return

    available = _available_heights(info)
    heights = [h for h in QUALITY_CHOICES if h <= MAX_HEIGHT and h in available]
    if not heights:
        # fallback: oferece a melhor disponível abaixo do limite configurado
        heights = sorted({h for h in available if h <= MAX_HEIGHT}, reverse=True)[:4]
    if not heights:
        await update.message.reply_text("❌ Nenhuma qualidade disponível dentro do limite.")
        return

    PENDING[update.effective_user.id] = url
    buttons = [
        InlineKeyboardButton(f"{h}p", callback_data=f"dl:{h}") for h in heights
    ]
    # uma linha de até 4 botões
    keyboard = InlineKeyboardMarkup([buttons])
    title = info.get("title", "vídeo")
    await update.message.reply_text(
        f"🎬 *{title}*\nEscolha a qualidade:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@restricted
async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    height = int(query.data.split(":", 1)[1])
    url = PENDING.pop(update.effective_user.id, None)
    if not url:
        await query.edit_message_text("⏱️ Sessão expirada. Mande o link de novo.")
        return

    await query.edit_message_text(f"⬇️ Baixando em {height}p...")

    out_path: Path | None = None
    try:
        out_path, info = await asyncio.to_thread(_download, url, height)
        size = out_path.stat().st_size
        if size > MAX_FILESIZE:
            await query.edit_message_text(
                f"⚠️ Arquivo ({size // (1024 * 1024)} MB) acima do limite "
                f"({MAX_FILESIZE // (1024 * 1024)} MB). Tente uma qualidade menor."
            )
            return

        await query.edit_message_text("📤 Enviando...")
        await query.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
        with out_path.open("rb") as fh:
            await query.message.reply_video(
                video=fh,
                caption=info.get("title", ""),
                supports_streaming=True,
                width=info.get("width"),
                height=info.get("height"),
                duration=info.get("duration"),
                read_timeout=600,
                write_timeout=600,
            )
        await query.edit_message_text("✅ Pronto!")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha no download/envio")
        await query.edit_message_text(f"❌ Erro: {exc}")
    finally:
        if out_path and out_path.exists():
            out_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Funções síncronas de yt-dlp (rodam em thread separada)
# --------------------------------------------------------------------------- #
def _extract_info(url: str) -> dict:
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:
        return ydl.extract_info(url, download=False)


def _available_heights(info: dict) -> set[int]:
    return {f["height"] for f in info.get("formats", []) if f.get("height")}


def _download(url: str, height: int) -> tuple[Path, dict]:
    token = uuid.uuid4().hex
    outtmpl = str(DOWNLOAD_DIR / f"{token}.%(ext)s")
    opts = {
        **_base_opts(),
        "format": (
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        ),
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
        # merge_output_format pode trocar a extensão para .mp4
        if not path.exists():
            mp4 = path.with_suffix(".mp4")
            if mp4.exists():
                path = mp4
    return path, info


def main():
    builder = Application.builder().token(TOKEN)
    if API_BASE_URL:
        logger.info("Usando Bot API local em %s (limite 2 GB)", API_BASE_URL)
        builder = builder.base_url(f"{API_BASE_URL}/bot").base_file_url(
            f"{API_BASE_URL}/file/bot"
        )
    app = builder.build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern=r"^dl:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info(
        "Bot iniciado. Allowlist: %s",
        "* (todos)" if ALLOW_ALL else (ALLOWED_USER_IDS or "(vazia!)"),
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
