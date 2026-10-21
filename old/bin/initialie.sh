#!/bin/bash
if [ "$(uname)" == "Darwin" ]; then
    repo=$(pwd)
elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
    repo="/data/wwwroot/MagicHub"
fi

cd $repo || exit

git remote -v
rm -rf .git
git init
#git branch -m "main"
git remote add origin git@github.com:archiguru/MagicHub.git
git add -A && git commit -m"first commit"
git push -u origin main --force
