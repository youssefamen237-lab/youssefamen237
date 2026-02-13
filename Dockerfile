FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    ffprobe \
    imagemagick \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ src/
COPY config/ config/
COPY .env.example .env.example

# Create necessary directories
RUN mkdir -p db logs cache assets/backgrounds assets/music assets/fonts

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default to single-cycle mode for Docker
ENTRYPOINT ["python", "src/brain.py", "--single-cycle"]
