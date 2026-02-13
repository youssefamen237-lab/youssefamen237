.PHONY: help install test run single-cycle analyse clean logs setup github-setup get-yt-token

help:
	@echo "🎬 Smart Shorts - Available Commands"
	@echo ""
	@echo "🚀 QUICK START:"
	@echo "  make github-setup - Setup GitHub Actions (interactive)"
	@echo "  make get-yt-token - Get YouTube Refresh Token"
	@echo "  make quick-fix    - Show quick fix for errors"
	@echo ""
	@echo "⚙️  SETUP:"
	@echo "  make setup        - Install all dependencies"
	@echo "  make install      - Install Python dependencies only"
	@echo "  make env-setup    - Create .env file from template"
	@echo ""
	@echo "▶️  RUNNING:"
	@echo "  make run          - Run full scheduler (continuous)"
	@echo "  make single-cycle - Run one production cycle"
	@echo "  make analyse      - Run analysis only"
	@echo ""
	@echo "🧹 MAINTENANCE:"
	@echo "  make clean        - Clean cache and temp files"
	@echo "  make logs         - Show recent logs"
	@echo "  make db-reset     - Reset database (WARNING)"
	@echo "  make verify       - Verify system setup"
	@echo ""
	@echo "🐳 DOCKER:"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-run   - Run with Docker"
	@echo ""
	@echo "🔧 DEVELOPMENT:"
	@echo "  make test         - Run tests (if available)"
	@echo "  make lint         - Lint Python code"
	@echo "  make github-actions-test - Test workflow syntax"
	@echo ""

setup: install
	@echo "🔧 Setting up Smart Shorts..."
	mkdir -p db logs cache assets/backgrounds assets/music assets/fonts
	@echo "✅ Setup complete!"

install:
	@echo "📦 Installing dependencies..."
	pip install -r requirements.txt
	@echo "✅ Dependencies installed!"

run:
	@echo "▶️  Starting Smart Shorts (continuous mode)..."
	python src/brain.py --schedule

single-cycle:
	@echo "▶️  Running single production cycle..."
	python src/brain.py --single-cycle

analyse:
	@echo "📊 Running analysis only..."
	python -c "from src.analytics import run_analytics; run_analytics()"

clean:
	@echo "🧹 Cleaning cache..."
	rm -rf cache/*
	rm -rf /tmp/shorts/*
	rm -rf /tmp/short_production/*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cache cleaned!"

logs:
	@echo "📋 Recent logs (last 50 lines):"
	@tail -50 logs/brain_*.log 2>/dev/null || echo "No logs found"

db-reset:
	@echo "⚠️  WARNING: This will reset the database!"
	@read -p "Are you sure? Type 'yes' to confirm: " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		rm -f db/system.db; \
		echo "✅ Database reset!"; \
	else \
		echo "❌ Cancelled"; \
	fi

test:
	@echo "🧪 Running tests..."
	@python -m pytest tests/ -v 2>/dev/null || echo "No test framework configured"

lint:
	@echo "🔍 Linting Python code..."
	@python -m pylint src/ --disable=all --enable=E 2>/dev/null || echo "Pylint not installed"

venv:
	@echo "📦 Creating virtual environment..."
	python -m venv venv
	@echo "✅ Virtual environment created!"
	@echo "Activate with: source venv/bin/activate"

env-setup:
	@echo "⚙️  Setting up .env file..."
	@test -f .env || cp .env.example .env
	@echo "✅ .env created! Edit it with your API keys"

version:
	@echo "Smart Shorts v2.0.0"

github-actions-test:
	@echo "🔍 Testing GitHub Actions workflow syntax..."
	@python -m pip install pyyaml > /dev/null 2>&1
	@python -c "import yaml; yaml.safe_load(open('.github/workflows/smart_shorts.yml'))" && echo "✅ Workflow syntax valid!" || echo "❌ Workflow has errors"

docker-build:
	@echo "🐳 Building Docker image..."
	docker build -t smart-shorts:latest .
	@echo "✅ Docker image built!"

docker-run:
	@echo "🐳 Running with Docker..."
	docker run -v $(PWD)/db:/app/db \
	          -v $(PWD)/logs:/app/logs \
	          -v $(PWD)/.env:/.env \
	          smart-shorts:latest

requirements-update:
	@echo "🔄 Updating requirements.txt..."
	pip list --format=freeze | sort > requirements_new.txt
	@echo "Review requirements_new.txt and replace requirements.txt if needed"

all: setup run

# New quick-start commands
github-setup:
	@echo "🚀 Interactive GitHub Setup"
	bash setup-github.sh

get-yt-token:
	@echo "🎬 Getting YouTube Refresh Token"
	python get-yt-token.py

quick-fix:
	@echo "📖 For quick fix, read: QUICK_FIX.md"
	@echo "For detailed help, read: GITHUB_ACTIONS_FIX.md"
	@cat QUICK_FIX.md

verify:
	@echo "🔍 Verifying system..."
	python verify_system.py
