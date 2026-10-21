#!/bin/bash
#################################################################
######### 此脚本用于 GitHub Action workflow，请勿直接使用！！！#######
#################################################################
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

echo
echo "******  更新规则集  ******"
python3 "${SCRIPT_DIR}/update_github_rules.py"

echo
echo "******  更新变更文件  ******"
git config user.name "GitHub Actions"
git config user.email jonny6015@icloud.com
git pull
git status -s
if [ -n "$(git status -s)" ]; then
    git add -A
    git commit -m "[Auto]SyncFiles"
    git push -u origin main --force
else
    echo "文件无变化，不做更新"
fi

echo "******  ✅ 完成更新文件  ******"
exit 0
