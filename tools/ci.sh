#!/usr/bin/env bash
# 本地/CI 统一门禁：文档预算、结构、完整性、公共包一致性和离线测试。
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "===== 1/6 上下文预算 ====="
python3 tools/measure_context.py --check

echo "===== 2/6 文档结构 ====="
python3 tools/check_skill_docs.py

echo "===== 3/6 技能完整性 ====="
python3 tools/check_skill_integrity.py

echo "===== 4/6 公共包副本 ====="
./vendor-common.sh --check

echo "===== 5/6 公共/工具单测 ====="
python3 -m unittest discover -s qa_skill_common/tests -q
python3 -m unittest discover -s tools/tests -q

echo "===== 6/6 技能单测 ====="
python3 -m unittest discover -s ones-create-linked-defect/scripts/tests -q
python3 -m unittest discover -s generate-arun-api-scripts/scripts/tests -q

echo "✓ CI 门禁全部通过"
