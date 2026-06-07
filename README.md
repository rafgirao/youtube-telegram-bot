# YouTube → Telegram Bot

Bot de Telegram que baixa **vídeos do YouTube** (com escolha de qualidade), restrito a
uma **allowlist de usuários**. Pronto para deploy no **EasyPanel** via Docker.

> ⚠️ **Aviso legal:** baixar vídeos do YouTube pode violar os Termos de Serviço do
> YouTube e direitos autorais. Use para conteúdo próprio, educacional ou em domínio
> público. A allowlist reduz o risco de abuso.

## Funcionalidades

- Escolha de qualidade via botões inline (1080p / 720p / 480p / 360p, filtrado pelo que
  o vídeo oferece e por `MAX_HEIGHT`).
- Acesso restrito por lista de IDs (`ALLOWED_USER_IDS`).
- Suporte a **arquivos até 2 GB** quando rodando com um Telegram Bot API server local
  (limite cai para 50 MB se usar o Bot API oficial).
- Limpa os arquivos do disco após o envio.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `TELEGRAM_TOKEN` | sim | Token do bot (via [@BotFather](https://t.me/BotFather)) |
| `ALLOWED_USER_IDS` | sim | IDs autorizados, separados por vírgula. Use `*` para liberar a todos (⚠️ bot público) |
| `MAX_HEIGHT` | não | Altura máxima oferecida (default `720`) |
| `TELEGRAM_API_BASE_URL` | não | URL do Bot API local (ativa limite de 2 GB) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | só p/ server local | De [my.telegram.org](https://my.telegram.org) |
| `YOUTUBE_COOKIES_B64` | em VPS | Cookies do YouTube em base64 (ver abaixo) |
| `COOKIES_FILE` | alternativa | Caminho de um `cookies.txt` montado |
| `YT_PLAYER_CLIENT` | não | Forçar clients, ex.: `android,ios,web` |
| `YT_PROXY` | alternativa | Proxy residencial p/ driblar bloqueio (cobra por GB) |
| `DOWNLOAD_DIR` | não | Pasta temporária (default `/tmp/dl`) |

### Alternativa aos cookies: proxy residencial

Em vez de cookies, dá para rotear o tráfego por um **IP residencial** (provedores:
Webshare, IPRoyal, Smartproxy, Bright Data). Não precisa de conta do YouTube, mas
⚠️ **cobra por GB de tráfego** — e vídeo consome muita banda. Configure:

```
YT_PROXY=http://usuario:senha@host:porta
```

Suporta `http://`, `https://` e `socks5://`. Pode ser combinado com cookies.

## Cookies do YouTube (obrigatório em VPS)

O YouTube bloqueia downloads de IPs de datacenter com *"Sign in to confirm you're not
a bot"*. A solução é fornecer cookies de uma conta logada (**use uma conta descartável**).

1. No navegador, instale a extensão **"Get cookies.txt LOCALLY"** (Chrome/Firefox).
2. Logue numa conta Google/YouTube descartável e exporte `cookies.txt` (formato Netscape).
3. Converta para base64 e use em `YOUTUBE_COOKIES_B64`:
   ```bash
   base64 -w0 cookies.txt   # Linux
   base64 -i cookies.txt    # macOS
   ```
4. Cole o resultado na variável `YOUTUBE_COOKIES_B64` no EasyPanel e faça redeploy.

> Os cookies expiram com o tempo; se voltar a falhar, exporte de novo.

**Como descobrir seu user ID:** fale com [@userinfobot](https://t.me/userinfobot), ou
mande qualquer mensagem ao bot — a resposta de "acesso negado" mostra seu ID.

## Rodando localmente

```bash
cp .env.example .env      # preencha TELEGRAM_TOKEN e ALLOWED_USER_IDS
docker compose up --build
```

Para o **modo simples (50 MB, sem server local)**: comente o serviço
`telegram-bot-api` no `docker-compose.yml`, remova `depends_on` e a env
`TELEGRAM_API_BASE_URL` do serviço `bot`.

Sem Docker:

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN=... ALLOWED_USER_IDS=123456789
python bot.py
```

## Deploy no EasyPanel

1. Dê push deste repositório no GitHub.
2. (Repo privado) EasyPanel → **Settings → GitHub** → conecte com um token fine-grained
   com acesso ao repo. ([docs](https://easypanel.io/docs/code-sources/github))
3. Crie um serviço **Compose** apontando para o repo + branch (usa o `docker-compose.yml`).
   - É um bot por **polling**: **não configure porta nem domínio** (é um worker).
     ([docs App Service](https://easypanel.io/docs/services/app))
4. Defina as **variáveis de ambiente** no painel (`TELEGRAM_TOKEN`, `ALLOWED_USER_IDS`,
   e — para 2 GB — `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`).
5. **Deploy** e acompanhe os logs. Cada push pode disparar rebuild automático.

## Estrutura

```
bot.py               # lógica do bot
requirements.txt     # dependências pinadas
Dockerfile           # imagem do bot (python + ffmpeg)
docker-compose.yml   # bot + telegram-bot-api server (2 GB)
.env.example         # template de variáveis
```

## Possíveis evoluções

Download de áudio/MP3, suporte a playlists, fila com rate-limit por usuário, barra de
progresso em tempo real, cookies para vídeos com restrição de idade/login.
