FROM python:3.13-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

# 配置/cookies/缓存/日志统一放在挂载卷
ENV FXXXXC_DATA_DIR=/config \
    PYTHONUNBUFFERED=1

RUN mkdir -p /config && \
    cp config_template.ini /config/config.ini

VOLUME /config

ENTRYPOINT ["python3", "main.py", "-c", "/config/config.ini"]
