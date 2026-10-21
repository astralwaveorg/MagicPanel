#!/usr/bin/env pwsh
#################################################################
######### 此脚本用于 GitHub Action workflow，请勿直接使用！！！#######
#################################################################

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $RepoRoot

function Invoke-Git {
    git @args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host
Write-Host "******  更新规则集  ******"
python3 (Join-Path $ScriptDir "update_github_rules.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host
Write-Host "******  更新变更文件  ******"
Invoke-Git config user.name "GitHub Actions"
Invoke-Git config user.email "jonny6015@icloud.com"
Invoke-Git pull
Invoke-Git status -s

$status = git status -s
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($status) {
    Invoke-Git add -A
    Invoke-Git commit -m "[Auto]SyncFiles"
    Invoke-Git push -u origin main --force
}
else {
    Write-Host "文件无变化，不做更新"
}

Write-Host "******  ✅ 完成更新文件  ******"
exit 0
