#!/bin/bash
if [ "$(uname)" == "Darwin" ]; then
    repo=$(pwd)
elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
    repo="/data/wwwroot/MagicHub"
fi

cd $repo || exit

git pull
git add -A
git commit -m "Update by script"
git push -u origin main
echo "Update Success!"
