#!/usr/bin/env bash
# ============================================================================
# sync-skills.sh —— 把 qa-skills 仓库技能同步到技能库，避免再次遗忘。
#
# 背景：Codex 实际加载 ~/.codex/skills/，DSH/其他运行时可能加载 ~/.agents/skills/。
#       两处都是独立副本，与仓库不同步；只同步一个根会造成“这边能跑、那边缺包”。
#
# 用法：
#   ./sync-skills.sh                     # 同步到 ~/.codex/skills 与 ~/.agents/skills
#   ./sync-skills.sh --dry-run           # 只预览会同步哪些文件，不真正执行
#   ./sync-skills.sh --purge             # 同步并删除目标侧「仓库没有」的文件（白名单除外）
#   ./sync-skills.sh --target <dir>      # 只同步到指定根（可重复）
#   ./sync-skills.sh --check             # 同 --dry-run
#   ./sync-skills.sh -h                  # 帮助
#
# 环境变量：
#   CODEX_SKILLS_DIR     兼容旧用法：只同步到该目录（未设置 SKILL_SYNC_TARGETS 时生效）
#   SKILL_SYNC_TARGETS   冒号分隔的多个根，例如 "$HOME/.codex/skills:$HOME/.agents/skills"
# ============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 仓库中需要同步的技能目录（按需增删）
SYNC_DIRS=(web-blackbox-testing web-adversarial-testing ones-create-linked-defect generate-manufacturing-test-cases generate-arun-api-scripts)

DRY_RUN=0
PURGE=0
RUN_INSTALL_CHECK=1
TARGETS=()

if [ -n "${SKILL_SYNC_TARGETS:-}" ]; then
  IFS=':' read -r -a _env_targets <<< "$SKILL_SYNC_TARGETS"
  TARGETS+=("${_env_targets[@]}")
elif [ -n "${CODEX_SKILLS_DIR:-}" ]; then
  TARGETS+=("$CODEX_SKILLS_DIR")
else
  TARGETS+=("$HOME/.codex/skills" "$HOME/.agents/skills")
fi

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --dry-run|--check)
      DRY_RUN=1
      ;;
    --purge)
      PURGE=1
      ;;
    --no-install-check)
      RUN_INSTALL_CHECK=0
      ;;
    --target)
      shift
      [ $# -gt 0 ] || { echo "--target 需要目录参数" >&2; exit 1; }
      # 显式 --target 覆盖默认根，避免“指定了一个却还同步另一个”。
      if [ "${#TARGETS[@]}" -gt 0 ] && [ "${TARGETS[0]}" != "$HOME/.codex/skills" ] && [ "${TARGETS[0]}" != "$HOME/.agents/skills" ]; then
        :
      else
        TARGETS=()
      fi
      TARGETS+=("$1")
      ;;
    --target=*)
      if [ "${#TARGETS[@]}" -gt 0 ] && [ "${TARGETS[0]}" != "$HOME/.codex/skills" ] && [ "${TARGETS[0]}" != "$HOME/.agents/skills" ]; then
        :
      else
        TARGETS=()
      fi
      TARGETS+=("${1#--target=}")
      ;;
    *)
      echo "未知参数: $1（支持 --dry-run / --check / --purge / --target / --no-install-check / -h）" >&2
      exit 1
      ;;
  esac
  shift
done

if [ "${#TARGETS[@]}" -eq 0 ]; then
  echo "没有可同步的目标根" >&2
  exit 1
fi

echo "仓库目录:   $REPO_DIR"
echo "目标目录:   ${TARGETS[*]}"
MODE="正式同步"
[ "$DRY_RUN" -eq 1 ] && MODE="DRY-RUN（仅预览）"
[ "$PURGE" -eq 1 ] && MODE="${MODE} + PURGE(删除目标侧仓库没有的文件)"
echo "模式:       $MODE"
echo

# ---- 前置闸门：文档结构 + 上下文预算（防「瘦身之后又长回去」） ----
if command -v python3 >/dev/null 2>&1; then
  echo "===== 前置闸门 ====="
  python3 "$REPO_DIR/tools/measure_context.py" --check >/tmp/qa_budget.log 2>&1 || {
    echo "  [失败] 上下文预算未通过，先修文档再同步：" >&2
    grep -E "✗|结果" /tmp/qa_budget.log | sed 's/^/    /' >&2
    exit 1
  }
  grep -E "^结果" /tmp/qa_budget.log | sed 's/^/  /'
  python3 "$REPO_DIR/tools/check_skill_docs.py" | tail -1 | sed 's/^/  /' || {
    echo "  [失败] 文档闸门未通过" >&2; exit 1; }
  if [ -f "$REPO_DIR/tools/check_skill_integrity.py" ]; then
    python3 "$REPO_DIR/tools/check_skill_integrity.py" | tail -1 | sed 's/^/  /' || {
      echo "  [失败] 完整性闸门未通过（敏感信息/链接/无引用脚本）" >&2; exit 1; }
  fi
  echo
else
  echo "[警告] 未找到 python3，跳过前置闸门"
fi

# 先把公共实现内置到各技能，保证每个技能单目录安装也能运行
if [ "$DRY_RUN" -eq 1 ]; then
  "$REPO_DIR/vendor-common.sh" --check \
    || echo "  [警告] 内置副本与 qa_skill_common/ 不一致；正式同步会自动重建"
else
  "$REPO_DIR/vendor-common.sh"
fi
echo

RSYNC_OPTS=(-a --exclude '.DS_Store' --exclude '.git')
[ "$DRY_RUN" -eq 1 ] && RSYNC_OPTS+=(-n -v)

sync_one_target() {
  local target="$1"
  echo "########## 目标: $target ##########"
  mkdir -p "$target"

  for d in "${SYNC_DIRS[@]}"; do
    if [ ! -d "$REPO_DIR/${d}" ]; then
      echo "[跳过] 仓库不存在: ${d}"
      continue
    fi
    echo "===== 同步 ${d}/ -> ${target}/${d}/ ====="
    if [ "$PURGE" -eq 1 ]; then
      local -a purge_opts=("${RSYNC_OPTS[@]}" --delete)
      # 白名单：目标侧本地运行时文件即使仓库没有也要保留，不被 --delete 删除
      case "$d" in
        web-blackbox-testing)
          purge_opts+=(--exclude 'scripts/config')
          ;;
        ones-create-linked-defect)
          purge_opts+=(--exclude 'scripts/config' --exclude 'config/field-mapping.local.yaml' --exclude 'bug-reports' --exclude 'test-reports')
          ;;
      esac
      rsync "${purge_opts[@]}" "$REPO_DIR/${d}/" "${target}/${d}/"
    else
      rsync "${RSYNC_OPTS[@]}" "$REPO_DIR/${d}/" "${target}/${d}/"
    fi
    echo
  done
}

for target in "${TARGETS[@]}"; do
  sync_one_target "$target"
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "（DRY-RUN 结束，未做任何修改）"
  exit 0
fi

echo "===== 同步完成，验证关键文件 ====="
for target in "${TARGETS[@]}"; do
  for d in "${SYNC_DIRS[@]}"; do
    if [ ! -d "${target}/${d}" ]; then
      echo "  [缺失] ${target}/${d}"
      continue
    fi
    if [ -f "${target}/${d}/SKILL.md" ]; then
      echo "  [OK] ${target}/${d}/SKILL.md"
    else
      echo "  [警告] ${target}/${d} 缺少 SKILL.md"
    fi
  done
done

if [ "$RUN_INSTALL_CHECK" -eq 1 ] && [ -f "$REPO_DIR/tools/check_install.py" ] && command -v python3 >/dev/null 2>&1; then
  echo
  echo "===== 安装自检 ====="
  for target in "${TARGETS[@]}"; do
    python3 "$REPO_DIR/tools/check_install.py" --root "$target" || exit 1
  done
fi

echo
echo "注意：目标目录中仓库没有的本地文件（如 scripts/config/databases.yaml）会被保留（rsync 不带 --delete）。"
