#!/bin/bash
# 🎬 Smart Shorts Setup Helper Script

echo "╔════════════════════════════════════════════════════════╗"
echo "║    Smart Shorts GitHub Actions Setup Helper            ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
print_section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Check prerequisites
print_section "System Check"

command -v python3 &> /dev/null && print_success "Python 3 found" || print_error "Python 3 not found"
command -v git &> /dev/null && print_success "Git found" || print_error "Git not found"

# Check if we're in a git repo
if [ -d ".git" ]; then
    print_success "Git repository found"
    REPO_URL=$(git config --get remote.origin.url)
    echo "Repository: $REPO_URL"
else
    print_error "Not a git repository"
fi

# Menu
print_section "Choose Setup Method"
echo ""
echo "1️⃣  Local Testing (with .env file)"
echo "2️⃣  GitHub Secrets Auto-Add (requires 'gh' CLI)"
echo "3️⃣  Manual GitHub Secrets (copy-paste)"
echo "4️⃣  Show Required Keys Only"
echo "5️⃣  Test Without API Keys (setup config only)"
echo ""
read -p "Choose (1-5): " choice

case $choice in
    1)
        print_section "Setup .env for Local Testing"
        
        if [ ! -f ".env" ]; then
            cp .env.local.example .env
            print_success ".env created from template"
        else
            print_warning ".env already exists"
        fi
        
        echo ""
        echo "Edit .env file with your credentials:"
        echo "  nano .env"
        echo ""
        echo "Then test with:"
        echo "  source .env && python src/brain.py --single-cycle"
        ;;
        
    2)
        print_section "GitHub Secrets with gh CLI"
        
        # Check if gh is installed
        if ! command -v gh &> /dev/null; then
            print_error "gh CLI not installed"
            echo ""
            echo "Install from: https://cli.github.com/"
            exit 1
        fi
        
        # Check if authenticated
        if ! gh auth status &> /dev/null; then
            print_error "Not authenticated with GitHub"
            echo ""
            echo "Run: gh auth login"
            exit 1
        fi
        
        print_warning "Make sure you have the following ready:"
        echo "  1. YT_CLIENT_ID_3"
        echo "  2. YT_CLIENT_SECRET_3"
        echo "  3. YT_REFRESH_TOKEN_3"
        echo "  4. YT_CHANNEL_ID"
        echo "  5. OPENAI_API_KEY (or GEMINI_API_KEY or GROQ_API_KEY)"
        echo ""
        
        # Collect keys
        read -p "Enter YT_CLIENT_ID_3: " yt_client_id
        read -p "Enter YT_CLIENT_SECRET_3: " yt_client_secret
        read -p "Enter YT_REFRESH_TOKEN_3: " yt_refresh_token
        read -p "Enter YT_CHANNEL_ID: " yt_channel_id
        read -p "Enter OPENAI_API_KEY: " openai_key
        
        # Add secrets
        print_section "Adding Secrets to GitHub"
        
        gh secret set YT_CLIENT_ID_3 --body "$yt_client_id" && print_success "YT_CLIENT_ID_3 added"
        gh secret set YT_CLIENT_SECRET_3 --body "$yt_client_secret" && print_success "YT_CLIENT_SECRET_3 added"
        gh secret set YT_REFRESH_TOKEN_3 --body "$yt_refresh_token" && print_success "YT_REFRESH_TOKEN_3 added"
        gh secret set YT_CHANNEL_ID --body "$yt_channel_id" && print_success "YT_CHANNEL_ID added"
        gh secret set OPENAI_API_KEY --body "$openai_key" && print_success "OPENAI_API_KEY added"
        
        echo ""
        print_success "All secrets added!"
        echo ""
        echo "Next: Push changes to trigger workflow"
        echo "  git add . && git commit -m 'Add workflow secrets' && git push"
        ;;
        
    3)
        print_section "Manual GitHub Secrets (Copy-Paste Method)"
        
        echo ""
        echo "📍 Follow these steps:"
        echo ""
        echo "1. Open your repository on GitHub"
        echo "2. Go: Settings → Secrets and variables → Actions"
        echo "3. Click 'New repository secret'"
        echo "4. Add each secret below:"
        echo ""
        echo "Required Secrets:"
        echo "   Name: YT_CLIENT_ID_3"
        echo "   Value: (from Google Cloud Console)"
        echo ""
        echo "   Name: YT_CLIENT_SECRET_3"
        echo "   Value: (from Google Cloud Console)"
        echo ""
        echo "   Name: YT_REFRESH_TOKEN_3"
        echo "   Value: (from OAuth2 code exchange)"
        echo ""
        echo "   Name: YT_CHANNEL_ID"
        echo "   Value: (your YouTube channel ID)"
        echo ""
        echo "   Name: OPENAI_API_KEY"
        echo "   Value: sk-... (from OpenAI platform)"
        echo ""
        echo "5. Save each secret"
        echo "6. Go to Actions tab and run workflow"
        echo ""
        print_warning "Find your Channel ID: go to YouTube Studio → Settings → About"
        ;;
        
    4)
        print_section "Required Keys Summary"
        
        echo ""
        echo "🔴 MANDATORY (Choose one):"
        echo "   • OPENAI_API_KEY: https://platform.openai.com"
        echo "   • GEMINI_API_KEY: https://makersuite.google.com"
        echo "   • GROQ_API_KEY: https://console.groq.com"
        echo ""
        echo "🔴 MANDATORY (YouTube):"
        echo "   • YT_CLIENT_ID_3: https://console.cloud.google.com"
        echo "   • YT_CLIENT_SECRET_3: (same place)"
        echo "   • YT_REFRESH_TOKEN_3: (run setup script)"
        echo "   • YT_CHANNEL_ID: (YouTube Studio)"
        echo ""
        echo "🟡 OPTIONAL (Enhance features):"
        echo "   • ELEVEN_API_KEY: Voice generation"
        echo "   • PEXELS_API_KEY: Stock images"
        echo "   • SERPAPI: Trends"
        echo "   • (and 20+ more)"
        echo ""
        echo "ℹ️  All optional keys are listed in .env.local.example"
        ;;
        
    5)
        print_section "Configuration Only Setup"
        
        echo ""
        echo "This will setup the project without requiring API keys."
        echo "You can generate content locally and test."
        echo ""
        
        # Check Python dependencies
        python3 -m pip install -r requirements.txt --quiet
        
        if [ $? -eq 0 ]; then
            print_success "Dependencies installed"
        else
            print_error "Failed to install dependencies"
            exit 1
        fi
        
        # Create directories
        mkdir -p db logs cache assets/{backgrounds,music}
        print_success "Directories created"
        
        # Verify
        python3 verify_system.py
        
        echo ""
        print_success "Setup complete!"
        echo ""
        echo "Next steps:"
        echo "1. Add API keys to GitHub Secrets (option 2 or 3)"
        echo "2. Or create .env file locally (option 1)"
        echo "3. Run: python src/brain.py --single-cycle"
        ;;
        
    *)
        print_error "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║ Setup Complete! 🎉                                     ║"
echo "║ For more help: Read GITHUB_ACTIONS_FIX.md              ║"
echo "╚════════════════════════════════════════════════════════╝"
