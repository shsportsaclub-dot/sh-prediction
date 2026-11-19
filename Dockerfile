# SH PREDICTION server image: our own Python code + free open-source tools (FFmpeg for video, Pillow for photos).
# Render builds this from the repo (runtime: docker); nothing is bought.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0
# Render sets PORT; the database and media live on the persistent disk mounted at /var/data.
CMD ["python", "app/main.py"]
