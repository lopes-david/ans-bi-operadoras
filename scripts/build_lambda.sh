#!/usr/bin/env bash
# Empacota o código + DuckDB (Linux ARM64) + extensão httpfs para a Lambda.
set -euo pipefail
cd "$(dirname "$0")/.."

ARCH="${LAMBDA_ARCH:-arm64}"   # arm64 (padrão, Graviton) ou x86_64
case "$ARCH" in
  arm64)  PY_PLATFORM=aarch64-manylinux_2_28; DUCK_PLATFORM=linux_arm64 ;;
  x86_64) PY_PLATFORM=x86_64-manylinux_2_28; DUCK_PLATFORM=linux_amd64 ;;
  *) echo "LAMBDA_ARCH inválido: $ARCH" >&2; exit 1 ;;
esac

OUT=build/lambda
rm -rf "$OUT" && mkdir -p "$OUT"

uv export --frozen --no-dev --no-emit-project --no-hashes -o build/requirements.txt >/dev/null
uv pip install --quiet --target "$OUT" --python-version 3.12 --python-platform "$PY_PLATFORM" \
  --only-binary=:all: -r build/requirements.txt

cp -r src/ans_bi "$OUT/"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +

DUCK_VERSION="v$(uv run --frozen python -c 'import duckdb; print(duckdb.__version__)')"
EXT_DIR="$OUT/ans_bi/duckdb_extensions/$DUCK_VERSION/$DUCK_PLATFORM"
mkdir -p "$EXT_DIR"
curl -fsSL "https://extensions.duckdb.org/$DUCK_VERSION/$DUCK_PLATFORM/httpfs.duckdb_extension.gz" \
  | gunzip > "$EXT_DIR/httpfs.duckdb_extension"

echo "pacote: $OUT ($(du -sh "$OUT" | cut -f1), duckdb $DUCK_VERSION, $ARCH)"
