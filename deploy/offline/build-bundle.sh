#!/bin/bash
# ============================================================
# 内网离线安装包构建脚本（architecture.md §10.2，M5）
#
# 在有外网的机器上执行，产出 deploy/offline/ 下的离线交付物:
#   backend-requirements.txt / backend-wheels/   L1 编排层依赖
#   runtime-requirements.txt / runtime-wheels/   运行时依赖
#     （含从本仓库源码构建的 agentscope wheel）
#   platform-dist/  平台前端静态产物 (pnpm build)
#   webui-dist/     运行时管理 UI 静态产物（凭证/模型注册用）
#
# wheels 目录较大（运行时约 400MB），不入 git（见 .gitignore）；
# requirements 快照入 git，作为交付依赖集的存档。
#
# 前提: 两个 venv 已按各自 README 初始化；node/pnpm 可用。
# 执行: bash deploy/offline/build-bundle.sh
# ============================================================
set -euo pipefail

BASE_DIR=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$BASE_DIR/deploy/offline"
BACKEND_PY="$BASE_DIR/platform/backend/.venv/Scripts/python.exe"
ROOT_PY="$BASE_DIR/.venv/Scripts/python.exe"
BACKEND_VENV_SITE="$BASE_DIR/platform/backend/.venv/Lib/site-packages"

mkdir -p "$OUT/backend-wheels" "$OUT/runtime-wheels"

echo "========== [1/5] L1 编排层依赖 =========="
# --path 只冻结该 venv，避免混入全局 site-packages
"$BACKEND_PY" -m pip freeze --path "$BACKEND_VENV_SITE" \
    | grep -v "^-e " > "$OUT/backend-requirements.txt"
"$BACKEND_PY" -m pip download -q \
    -r "$OUT/backend-requirements.txt" -d "$OUT/backend-wheels"
echo "backend: $(ls "$OUT/backend-wheels" | wc -l) 个 wheel"

echo "========== [2/5] 运行时依赖 =========="
# 根 venv 是 agentscope editable 安装: 冻结时剔除 -e 行,
# agentscope 本体在下一步从源码出 wheel
"$ROOT_PY" -m pip freeze \
    | grep -v "^-e " \
    | grep -viE "^(pip|setuptools|wheel)==" \
    > "$OUT/runtime-requirements.txt"
"$ROOT_PY" -m pip download -q \
    -r "$OUT/runtime-requirements.txt" -d "$OUT/runtime-wheels"
echo "runtime deps: $(ls "$OUT/runtime-wheels" | wc -l) 个 wheel"

echo "========== [3/5] agentscope 源码 wheel =========="
"$ROOT_PY" -m pip wheel --no-deps -q \
    -w "$OUT/runtime-wheels" "$BASE_DIR"
ls "$OUT/runtime-wheels" | grep -i "^agentscope" || true

echo "========== [4/5] 平台前端构建 =========="
export PATH="/c/Program Files/nodejs:/c/Users/58369/AppData/Roaming/npm:$PATH"
pnpm --dir "$BASE_DIR/platform/frontend" build \
    >/dev/null 2>&1 || pnpm --dir "$BASE_DIR/platform/frontend" build
rm -rf "$OUT/platform-dist"
cp -r "$BASE_DIR/platform/frontend/dist" "$OUT/platform-dist"
echo "platform-dist: $(find "$OUT/platform-dist" -type f | wc -l) 个文件"

echo "========== [5/5] 运行时管理 UI 构建 =========="
# web_ui 是 pnpm workspace（frontend + backend）: 管理员在内网用它注册
# 凭证/模型。构建产物在其子包目录里，随包结构一起拷贝。
pnpm --dir "$BASE_DIR/examples/web_ui" build >/dev/null
echo "web_ui 构建完成（examples/web_ui 整目录随源码进内网）"

echo ""
echo "离线包就绪: $OUT"
echo "  拷贝整个 deploy/offline/ + 仓库源码到内网，按 README-zh.md 部署"
