#!/usr/bin/env bash
# Run once from the repository root to create all required __init__.py files
set -e
PACKAGES=(
    analytics
    bootstrap
    cascade
    cascade/ai_images
    cascade/footage
    cascade/images
    cascade/llm
    cascade/tts
    channel_os
    data
    data/seeds
    engines
    intelligence
    pipelines
    protection
    reporting
    storage
    youtube
    youtube/management
    youtube/upload
)
for pkg in "${PACKAGES[@]}"; do
    mkdir -p "$pkg"
    touch "$pkg/__init__.py"
done
echo "Created __init__.py in ${#PACKAGES[@]} packages."
