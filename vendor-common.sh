#!/usr/bin/env bash
# ============================================================================
# vendor-common.sh —— 把公共实现包 qa_skill_common 内置到各技能，使每个技能
# 可独立安装（单独拷贝某个技能目录也能跑，不再依赖同级 qa_skill_common）。
#
# 背景：Codex 技能是「一个目录一个技能」，技能市场/单独安装只会拷走技能目录本身。
#       因此依赖不能只靠目录摆放约定，必须随技能一起分发。
#
# 用法：
#   ./vendor-common.sh          # 从 qa_skill_common/ 生成到各技能的 scripts/qa_skill_common/
#   ./vendor-common.sh --check  # 只校验副本是否与源头一致（CI/提交前用），不一致返回 1
#   ./vendor-common.sh -h       # 帮助
#
# 单一来源：公共实现只维护 qa_skill_common/，各技能内的副本由本脚本生成，勿手改。
# ============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/qa_skill_common"

# 需要内置公共包的技能（目录名）
TARGET_SKILLS=(web-blackbox-testing ones-create-linked-defect)

# 不参与内置的文件（仅开发侧文档/缓存）
EXCLUDES=(--exclude 'README.md' --exclude '__pycache__' --exclude '.DS_Store')

MODE=sync
for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --check) MODE=check ;;
    *) echo "未知参数: $arg（支持 --check / -h）" >&2; exit 1 ;;
  esac
done

[ -d "$SRC" ] || { echo "源目录不存在: $SRC" >&2; exit 1; }

failed=0
for skill in "${TARGET_SKILLS[@]}"; do
  dst="$REPO_DIR/$skill/scripts/qa_skill_common"
  if [ "$MODE" = check ]; then
    if [ ! -d "$dst" ]; then
      echo "[缺失] $skill/scripts/qa_skill_common"; failed=1; continue
    fi
    if diff -r -x README.md -x '__pycache__' -x '.DS_Store' "$SRC" "$dst" >/dev/null 2>&1; then
      echo "[一致] $skill/scripts/qa_skill_common"
    else
      echo "[漂移] $skill/scripts/qa_skill_common 与 qa_skill_common/ 不一致"
      diff -rq -x README.md -x '__pycache__' -x '.DS_Store' "$SRC" "$dst" || true
      failed=1
    fi
  else
    mkdir -p "$dst"
    rsync -a --delete "${EXCLUDES[@]}" "$SRC/" "$dst/"
    echo "[已内置] $skill/scripts/qa_skill_common"
  fi
done

if [ "$MODE" = check ] && [ "$failed" -ne 0 ]; then
  echo "校验失败：请运行 ./vendor-common.sh 重新生成。" >&2
  exit 1
fi
