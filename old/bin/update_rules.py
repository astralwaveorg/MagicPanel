#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脚本功能：根据配置文件下载并处理Surge规则，生成规则文件
配置文件格式：YAML，包含规则文件名、数据源URL列表和自定义
"""
import os
import re
import urllib.error
import urllib.request
from datetime import datetime

import yaml


CONFIG_FILE = "surge/rules/rules.yaml"
OUTPUT_DIR = "surge/rules"


def download_content(url):
    """
    下载指定URL的内容，返回字符串
    :param url: 要下载的URL
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"下载失败 {url}: {e}")
        return ""


def process_rules(content_list):
    """
    处理规则内容，去除注释和空行，返回有效规则集合

    :param content_list: 要处理的规则内容列表
    """
    valid_rules = set()
    comment_pattern = re.compile(r"^\s*(#|//|;)")
    for line in content_list:
        line = line.strip()
        if not line:
            continue
        if comment_pattern.match(line):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        valid_rules.add(line)
    return valid_rules


def main():
    """
    主函数，读取配置文件，下载并处理规则，生成输出文件
    """
    print("开始更新规则...")

    if not os.path.exists(CONFIG_FILE):
        print(f"配置文件不存在: {CONFIG_FILE}")
        exit(1)

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"配置文件解析失败: {e}")
        exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for filename, data in config.items():
        target_path = os.path.join(OUTPUT_DIR, filename)
        print(f"\n处理目标: {filename}")
        all_rules = set()

        sources = data.get("sources", [])
        for url in sources:
            content = download_content(url)
            if content:
                cleaned = process_rules(content.splitlines())
                all_rules.update(cleaned)

        custom_rules = data.get("rules", [])
        if custom_rules:
            cleaned_custom = process_rules(custom_rules)
            all_rules.update(cleaned_custom)

        sorted_rules = sorted(list(all_rules))
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(f"# 规则文件: {filename}\n")
                f.write(f"# 规则总数: {len(sorted_rules)}\n")
                f.write(
                    f"# 规则地址: https://list.magichub.top/d/surge/rules/{filename}\n"
                )
                f.write(f"# 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n")
                f.write("\n".join(sorted_rules))
            print(f"已写入 {len(sorted_rules)} 条规则至 {target_path}")
        except (IOError, OSError) as e:
            print(f"文件写入失败: {e}")

    print("\n所有任务已完成。")


if __name__ == "__main__":
    main()
