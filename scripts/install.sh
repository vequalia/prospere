#!/bin/bash

# Prospere One-Click Installer
# Support: macOS and Linux

set -e

# ANSI Color Codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting Prospere installation...${NC}"

# 1. Check for Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Error: Python 3 is not installed. Please install Python 3.11 or higher.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo -e "${GREEN}✅ Found Python $PYTHON_VERSION${NC}"

# 2. Define install directory
INSTALL_DIR="$HOME/.prospere"
VENV_DIR="$INSTALL_DIR/venv"

echo -e "${BLUE}📂 Setting up environment in $INSTALL_DIR...${NC}"
mkdir -p "$INSTALL_DIR"

# 3. Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# 4. Install Prospere from GitHub
echo -e "${BLUE}📥 Downloading and installing Prospere from GitHub...${NC}"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install "git+https://github.com/vequalia/prospere.git"

# 5. Create a wrapper script
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
cat <<EOF > "$BIN_DIR/prospere"
#!/bin/bash
export PATH="$VENV_DIR/bin:\$PATH"
exec "$VENV_DIR/bin/prospere" "\$@"
EOF
chmod +x "$BIN_DIR/prospere"

# 6. Configure Shell (Path and Alias)
SHELL_TYPE=$(basename "$SHELL")
CONFIG_FILE=""
if [ "$SHELL_TYPE" == "zsh" ]; then
    CONFIG_FILE="$HOME/.zshrc"
elif [ "$SHELL_TYPE" == "bash" ]; then
    CONFIG_FILE="$HOME/.bashrc"
fi

echo -e "${BLUE}🔧 Configuring your shell ($SHELL_TYPE)...${NC}"

# Add to PATH if not present
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    if [ -n "$CONFIG_FILE" ]; then
        echo -e "\n# Prospere Configuration" >> "$CONFIG_FILE"
        echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$CONFIG_FILE"
    fi
fi

# Add alias for maximum priority (fixes path conflict issues)
if [ -n "$CONFIG_FILE" ]; then
    if ! grep -q "alias prospere=" "$CONFIG_FILE"; then
        echo "alias prospere='$BIN_DIR/prospere'" >> "$CONFIG_FILE"
    fi
fi

echo -e "${GREEN}🎉 Prospere installed successfully!${NC}"

# 7. Final Sanity Check & Guidance
CURRENT_PROSPERE=$(which prospere || echo "none")
if [[ "$CURRENT_PROSPERE" != *".local/bin/prospere"* && "$CURRENT_PROSPERE" != "none" ]]; then
    echo -e "${YELLOW}⚠️  Note: We detected another 'prospere' command already on your system.${NC}"
    echo -e "${YELLOW}👉 To use this new version, please run:${NC} ${GREEN}source $CONFIG_FILE${NC}"
    echo -e "${YELLOW}👉 If it still fails, use the full path:${NC} ${BLUE}$BIN_DIR/prospere${NC}"
else
    echo -e "${GREEN}👉 Please run 'source $CONFIG_FILE' to start using Prospere.${NC}"
fi

echo -e "---"
