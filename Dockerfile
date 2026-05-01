FROM python:3.12-slim

# Install system dependencies for audio processing and voice connections
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        # Voice connection dependencies
        libopus0 \
        libsodium23 \
        libffi-dev \
        # Additional audio libraries that may help with voice
        libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Note: Voice connections require outbound UDP access (ports 50000-65535)
# Ensure your Docker network allows UDP traffic for Discord voice functionality
CMD ["python", "bot.py"]
