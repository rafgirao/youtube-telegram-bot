FROM python:3.12-slim

# ffmpeg é necessário para mesclar vídeo + áudio (yt-dlp)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Bot usa long polling — não expõe porta (é um worker).
CMD ["python", "bot.py"]
