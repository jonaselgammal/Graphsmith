#!/usr/bin/env bash
set -euo pipefail

# Graphsmith installer
# Creates a virtual environment and installs dependencies.
# Safe to rerun.

VENV_DIR=".venv"
MIN_PYTHON="3.11"

echo ""
echo "  Graphsmith Installer"
echo "  ===================="
echo ""

# ── Check Python ──────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python >= $MIN_PYTHON first."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python >= $MIN_PYTHON required (found $PY_VERSION)."
    exit 1
fi
echo "  [OK] Python $PY_VERSION"

# ── Create venv ───────────────────────────────────────────────────

if [ -d "$VENV_DIR" ]; then
    echo "  [OK] Virtual environment exists ($VENV_DIR)"
else
    echo "  Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "  [OK] Created $VENV_DIR"
fi

# ── Activate and install ──────────────────────────────────────────

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "  Installing Graphsmith..."
pip install -e ".[dev]" --quiet 2>&1 | tail -1 || pip install -e ".[dev]" --quiet
echo "  [OK] Graphsmith installed"

# ── Optional: scikit-learn for learned reranker ───────────────────

if python3 -c "import sklearn" 2>/dev/null; then
    echo "  [OK] scikit-learn available"
else
    echo "  Installing scikit-learn (optional, for learned reranker)..."
    pip install scikit-learn --quiet 2>/dev/null || true
fi

# ── API key setup ─────────────────────────────────────────────────

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo ""
        echo "  Created .env from .env.example."
        echo "  Edit .env and add your API keys:"
        echo ""
        echo "    GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-..."
        echo "    GRAPHSMITH_GROQ_API_KEY=gsk_..."
        echo ""
    fi
else
    echo "  [OK] .env file exists"
fi

# ── Done ──────────────────────────────────────────────────────────

echo ""
echo "  Done! Next steps:"
echo ""
echo "    source $VENV_DIR/bin/activate"
echo "    graphsmith doctor"
echo "    graphsmith run"
echo ""
