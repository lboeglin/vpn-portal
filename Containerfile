FROM python:3.11-slim

# WireGuard tools + iproute2 for interface management
RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-tools \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies before copying source (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
