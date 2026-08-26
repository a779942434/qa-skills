#!/usr/bin/env bash
# ============================================================================
# sync-skills.sh —— 把 qa-skills 仓库技能同步到 Codex 技能库，避免再次遗忘。
#
# 背景：Codex 实际加载 ~/.codex/skills/ 下的独立副本，与仓库不同步。
#       改完仓库后必须执行本脚本，codex 才会用上新版本。
#
# 用法：
#   ./sync-skills.sh               # 正式同步（保留目标侧本地 config 等独有文件）
#   ./sync-skills.sh --dry-run     # 只预览会同步哪些文件，不真正执行
#   ./sync-skills.sh --purge       # 同步并删除目标侧「仓库没有」的文件（白名单除外）
#   ./sync-skills.sh --dry-run --purge  # 先预览将删除的文件
#   ./sync-skills.sh -h            # 帮助
#
# 环境变量：
#   CODEX_SKILLS_DIR   目标目录，默认 $HOME/.codex/skills
# ============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_SKILLS_DIR="${CODEX_SKILLS_DIR:-$HOME/.codex/skills}"

# 仓库中需要同步到 Codex 的技能/公共包目录（按需增删）
SYNC_DIRS=(web-blackbox-testing qa_skill_common ones-create-linked-defect generate-manufacturing-test-cases generate-arun-api-scripts)

DRY_RUN=0
PURGE=0
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --dry-run|--check)
      DRY_RUN=1
      ;;
    --purge)
      PURGE=1
      ;;
    *)
      echo "未知参数: $arg（支持 --dry-run / --check / --purge / -h）" >&2
      exit 1
      ;;
  esac
done

echo "仓库目录:   $REPO_DIR"
echo "目标目录:   $CODEX_SKILLS_DIR"
MODE="正式同步"
[ "$DRY_RUN" -eq 1 ] && MODE="DRY-RUN（仅预览）"
[ "$PURGE" -eq 1 ] && MODE="${MODE} + PURGE(删除目标侧仓库没有的文件)"
echo "模式:       $MODE"
echo

mkdir -p "$CODEX_SKILLS_DIR"

RSYNC_OPTS=(-av --exclude '.DS_Store' --exclude '.git')
[ "$DRY_RUN" -eq 1 ] && RSYNC_OPTS+=(-n)

for d in "${SYNC_DIRS[@]}"; do
  if [ ! -d "$REPO_DIR/${d}" ]; then
    echo "[跳过] 仓库不存在: ${d}"
    continue
  fi
  echo "===== 同步 ${d}/ -> $CODEX_SKILLS_DIR/${d}/ ====="
  if [ "$PURGE" -eq 1 ]; then
    PURGE_OPTS=("${RSYNC_OPTS[@]}" --delete)
    # 白名单：这些目标侧本地运行时文件即使仓库没有也要保留，不被 --delete 删除
    case "$d" in
      web-blackbox-testing)
        PURGE_OPTS+=(--exclude 'scripts/config')
        ;;
      ones-create-linked-defect)
        PURGE_OPTS+=(--exclude 'config/field-mapping.local.yaml' --exclude 'bug-reports' --exclude 'test-reports')
        ;;
    esac
    rsync "${PURGE_OPTS[@]}" "$REPO_DIR/${d}/" "$CODEX_SKILLS_DIR/${d}/"
  else
    rsync "${RSYNC_OPTS[@]}" "$REPO_DIR/${d}/" "$CODEX_SKILLS_DIR/${d}/"
  fi
  echo
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "（DRY-RUN 结束，未做任何修改）"
  exit 0
fi

echo "===== 同步完成，验证关键文件 ====="
for d in "${SYNC_DIRS[@]}"; do
  if [ ! -d "$CODEX_SKILLS_DIR/${d}" ]; then
    echo "  [缺失] ${d}"
    continue
  fi
  # qa_skill_common 是公共实现包，无 SKILL.md 属正常
  if [ -f "$CODEX_SKILLS_DIR/${d}/SKILL.md" ]; then
    echo "  [OK] ${d}/SKILL.md"
  elif [ "${d}" = "qa_skill_common" ]; then
    echo "  [OK] ${d}（公共实现包，无 SKILL.md 属正常）"
  else
    echo "  [警告] ${d} 缺少 SKILL.md"
  fi
done
echo
echo "注意：目标目录中仓库没有的本地文件（如 scripts/config/databases.yaml）会被保留（rsync 不带 --delete）。"
