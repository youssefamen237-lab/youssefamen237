FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    fontconfig \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p out state data assets/backgrounds

# Set environment
ENV PYTHONUNBUFFERED=1

# Default command
CMD ["python", "-m", "yt_auto", "short", "--slot", "1"]
