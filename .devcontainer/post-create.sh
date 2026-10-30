#!/usr/bin/env bash
set -euo pipefail


echo "==> Instalando uv (usado pelo serverless-python-requirements nativo)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Instalando dependências Python de desenvolvimento"
python -m pip install --upgrade pip
if [ -f requirements-dev.txt ]; then
  pip install -r requirements-dev.txt
else
  # Dependências mínimas de desenvolvimento/teste até requirements-dev.txt existir
  pip install pytest moto boto3 duckdb ruff
fi

apk add --no-cache python3 py3-pip

echo "==> Verificando ferramentas"
python --version
node --version
serverless --version || true
aws --version || true
uv --version || true

echo "==> Ambiente pronto."
