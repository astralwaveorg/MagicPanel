# -*- coding: utf-8 -*-
import requests
import yaml
import os
import logging
import hashlib
import time

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 配置 ---
# GitHub仓库中的文件夹路径
CLASH_DIR = "clash"
SURGE_DIR = "surge"
# 新生成的文件名
CLASH_FILE = "list.yaml"
SURGE_FILE = "list.ini"

# --- Telegram Bot 配置 ---
# 是否启用 Telegram 告警
ENABLE_TELEGRAM_ALERTS = True
TELEGRAM_BOT_TOKEN = "7717018566:AAETzjkQGL1NgKNkZvvRSd7P3Oibuk6v8tU"  # 请确认这个token是正确的
TELEGRAM_CHAT_ID = "-1002525135181"

# --- 告警频率控制 ---
ALERT_COOLDOWN_MINUTES = 60  # 相同错误的最小告警间隔（分钟）
LAST_ALERT_FILE = "last_alert.json"  # 存储上次告警时间的文件

# --- 订阅链接 (支持多个) ---
CLASH_URLS = [
    "https://api-huacloud.net/sub?target=clash&insert=true&emoji=true&udp=true&clash.doh=true&new_name=true&filename=Flower_Trojan.yaml&url=https%3A%2F%2Fapi.xmancdn.net%2Fosubscribe.php%3Ftoken2%3Dey7844dq-25cf2d551959cpg8o1"
]

SURGE_URLS = [
    "https://api-huacloud.net/sub?target=surge&ver=4&insert=true&emoji=true&tfo=true&udp=true&surge.doh=true&filename=Flower_Trojan.conf&url=https%3A%2F%2Fapi.xmancdn.net%2Fosubscribe.php%3Ftoken2%3Dey7844dq-25cf2d551959cpg8o1"
]

# 过滤关键词黑名单，名称中包含关键词的节点将被过滤掉
CLASH_BLACKLIST = ["Traffic", "Expire", "剩余流量", "过期时间"]
SURGE_BLACKLIST = ["Traffic", "Expire", "剩余流量", "过期时间"]


# --- 告警频率控制函数 ---
def should_alert_for_errors(current_errors):
    """
    判断是否应该发送告警，避免频繁告警
    :param current_errors: 当前错误列表
    :return: (bool, str) 是否应该告警，以及原因
    """
    if not current_errors:
        return False, "没有错误"

    # 生成当前错误的指纹（用于判断是否与上次相同）
    error_fingerprint = hashlib.md5("|".join(sorted(current_errors)).encode()).hexdigest()

    # 读取上次告警信息
    last_alert_time = 0
    last_error_fingerprint = ""

    try:
        if os.path.exists(LAST_ALERT_FILE):
            with open(LAST_ALERT_FILE, 'r') as f:
                import json
                data = json.load(f)
                last_alert_time = data.get('last_alert_time', 0)
                last_error_fingerprint = data.get('error_fingerprint', "")
    except Exception as e:
        logging.warning(f"读取上次告警记录失败: {e}")

    current_time = time.time()
    cooldown_seconds = ALERT_COOLDOWN_MINUTES * 60

    # 如果是新错误，立即告警
    if error_fingerprint != last_error_fingerprint:
        logging.info("检测到新错误模式，需要告警")
        return True, "新错误模式"

    # 如果是相同错误，检查冷却时间
    if current_time - last_alert_time < cooldown_seconds:
        remaining = (cooldown_seconds - (current_time - last_alert_time)) / 60
        logging.info(f"相同错误在冷却期内，{remaining:.1f}分钟后可再次告警")
        return False, f"冷却期内，{remaining:.1f}分钟后可告警"

    logging.info("相同错误但已过冷却期，需要告警")
    return True, "冷却期已过"


def update_alert_record(current_errors):
    """
    更新告警记录
    :param current_errors: 当前错误列表
    """
    if not current_errors:
        return

    error_fingerprint = hashlib.md5("|".join(sorted(current_errors)).encode()).hexdigest()

    try:
        with open(LAST_ALERT_FILE, 'w') as f:
            import json
            data = {
                'last_alert_time': time.time(),
                'error_fingerprint': error_fingerprint,
                'last_alert_count': len(current_errors)
            }
            json.dump(data, f)
        logging.info("已更新告警记录")
    except Exception as e:
        logging.error(f"更新告警记录失败: {e}")


def send_telegram_alert(messages):
    """
    发送一个汇总的告警消息到 Telegram.
    :param messages: 一个包含所有错误信息的列表.
    """
    if not ENABLE_TELEGRAM_ALERTS or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram 告警未启用或未配置 Token/Chat ID，错误将仅打印在控制台。")
        return False

    if not messages:
        logging.info("没有错误，跳过 Telegram 告警。")
        return True

    # 检查是否应该告警
    should_alert, reason = should_alert_for_errors(messages)
    if not should_alert:
        logging.info(f"跳过告警: {reason}")
        return True

    # 格式化告警消息
    summary_message = "🚨 脚本运行异常告警 (共 {} 条)\n⏰ 时间: {}\n\n".format(
        len(messages),
        time.strftime("%Y-%m-%d %H:%M:%S")
    )

    # 添加错误详情
    for i, msg in enumerate(messages, 1):
        summary_message += f"{i}. {msg}\n"

    # 添加频率控制说明
    summary_message += f"\n📊 告警频率控制: 相同错误 {ALERT_COOLDOWN_MINUTES} 分钟内只告警一次"

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': summary_message,
        'parse_mode': 'Markdown'
    }

    try:
        response = requests.post(api_url, json=payload, timeout=20)
        response.raise_for_status()
        logging.info("成功发送 Telegram 告警消息。")

        # 更新告警记录
        update_alert_record(messages)
        return True

    except requests.exceptions.RequestException as e:
        logging.error(f"发送 Telegram 消息失败: {e}")

        # 如果是 token 错误，给出具体提示
        if "400" in str(e) and "bad token" in str(e).lower():
            logging.error("❌ Telegram Bot Token 可能无效，请检查配置")
        elif "400" in str(e):
            logging.error("❌ 请求参数错误，可能是 Chat ID 或 Token 格式问题")
        elif "401" in str(e):
            logging.error("❌ Unauthorized，Token 无效")
        elif "403" in str(e):
            logging.error("❌ Forbidden，Bot 没有权限向该 Chat ID 发送消息")
        elif "404" in str(e):
            logging.error("❌ Chat ID 或 Bot 不存在")

        logging.error("以下是未能发送的原始错误信息:")
        for msg in messages:
            logging.error(f"- {msg}")
        return False


def download_content(url):
    """
    从给定的 URL 下载内容。
    如果下载失败，会抛出异常。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
    }
    response = requests.get(url, timeout=20, headers=headers)
    response.raise_for_status()
    return response.text


def ensure_directory_exists(directory):
    """确保指定的目录存在，如果不存在则创建。"""
    if not os.path.exists(directory):
        os.makedirs(directory)


def process_clash_subscriptions(urls, blacklist, error_collector):
    """
    下载、解析、合并、过滤并保存所有 Clash 配置。
    :param urls: Clash 订阅链接列表.
    :param blacklist: 关键词黑名单.
    :param error_collector: 用于收集错误信息的列表.
    """
    logging.info(">>> 开始处理 Clash 订阅...")
    all_proxies = []

    for i, url in enumerate(urls, 1):
        logging.info(f"处理 Clash 链接 ({i}/{len(urls)}): {url[:50]}...")
        try:
            raw_content = download_content(url)
            data = yaml.safe_load(raw_content)

            if "proxies" in data and isinstance(data["proxies"], list):
                original_count = len(data["proxies"])
                filtered_proxies = [
                    proxy for proxy in data["proxies"]
                    if "name" in proxy and isinstance(proxy["name"], str) and not any(keyword in proxy["name"] for keyword in blacklist)
                ]
                all_proxies.extend(filtered_proxies)
                logging.info(f"链接处理成功，原始节点: {original_count}，过滤后剩余: {len(filtered_proxies)}")
            else:
                raise ValueError("订阅内容中未找到 'proxies' 列表。")
        except Exception as e:
            error_msg = f"Clash 链接失败: {url[:60]}... | 原因: {str(e)[:100]}"
            logging.error(error_msg)
            error_collector.append(error_msg)

    if not all_proxies:
        if not any("Clash" in msg for msg in error_collector):  # 避免重复添加
            error_msg = "Clash: 未能从任何链接中成功解析出节点"
            logging.error(error_msg)
            error_collector.append(error_msg)
        return

    # 创建新的 YAML 数据结构并保存
    final_clash_data = {"proxies": all_proxies}
    output_path = os.path.join(CLASH_DIR, CLASH_FILE)
    ensure_directory_exists(CLASH_DIR)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(final_clash_data, f, allow_unicode=True, sort_keys=False)
        logging.info(f"成功合并并保存 Clash 配置到 {output_path}，共 {len(all_proxies)} 个节点。")
    except IOError as e:
        error_msg = f"写入 Clash 文件失败: {output_path} | 原因: {e}"
        logging.error(error_msg)
        error_collector.append(error_msg)


def process_surge_subscriptions(urls, blacklist, error_collector):
    """
    下载、解析、合并、过滤并保存所有 Surge 配置。
    :param urls: Surge 订阅链接列表.
    :param blacklist: 关键词黑名单.
    :param error_collector: 用于收集错误信息的列表.
    """
    logging.info(">>> 开始处理 Surge 订阅...")
    all_proxy_lines = []

    for i, url in enumerate(urls, 1):
        logging.info(f"处理 Surge 链接 ({i}/{len(urls)}): {url[:50]}...")
        try:
            raw_content = download_content(url)
            proxy_section_started = False
            lines = raw_content.split('\n')

            original_count = 0
            filtered_count = 0

            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                if line_stripped == "[Proxy]":
                    proxy_section_started = True
                    continue

                # 如果遇到其他 section，则停止解析
                if proxy_section_started and line_stripped.startswith('['):
                    break

                if proxy_section_started:
                    original_count += 1
                    # 过滤注释和黑名单
                    if not line_stripped.startswith(';') and not line_stripped.startswith('#') and not any(keyword in line_stripped for keyword in blacklist):
                        all_proxy_lines.append(line)
                        filtered_count += 1

            if not proxy_section_started:
                raise ValueError("订阅内容中未找到 '[Proxy]' 部分。")
            logging.info(f"链接处理成功，原始节点: {original_count}，过滤后剩余: {filtered_count}")

        except Exception as e:
            error_msg = f"Surge 链接失败: {url[:60]}... | 原因: {str(e)[:100]}"
            logging.error(error_msg)
            error_collector.append(error_msg)

    if not all_proxy_lines:
        if not any("Surge" in msg for msg in error_collector):  # 避免重复添加
            error_msg = "Surge: 未能从任何链接中成功解析出节点"
            logging.error(error_msg)
            error_collector.append(error_msg)
        return

    # 创建新的 Surge 配置文件内容并保存
    new_surge_content = "[Proxy]\n" + "\n".join(all_proxy_lines) + "\n"
    output_path = os.path.join(SURGE_DIR, SURGE_FILE)
    ensure_directory_exists(SURGE_DIR)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(new_surge_content)
        logging.info(f"成功合并并保存 Surge 配置到 {output_path}，共 {len(all_proxy_lines)} 个节点。")
    except IOError as e:
        error_msg = f"写入 Surge 文件失败: {output_path} | 原因: {e}"
        logging.error(error_msg)
        error_collector.append(error_msg)


# --- 主程序入口 ---
if __name__ == "__main__":
    # 创建一个列表来收集整个运行过程中的所有错误
    error_messages = []

    process_clash_subscriptions(CLASH_URLS, CLASH_BLACKLIST, error_messages)
    process_surge_subscriptions(SURGE_URLS, SURGE_BLACKLIST, error_messages)

    # 检查是否有错误发生，并发送告警
    if error_messages:
        logging.info(f"脚本运行期间检测到 {len(error_messages)} 个错误，准备发送告警...")
        alert_sent = send_telegram_alert(error_messages)
        if alert_sent:
            logging.info("告警已发送")
        else:
            logging.error("告警发送失败")
    else:
        logging.info("所有任务成功完成，没有错误。")
        # 清除之前的告警记录（如果之前有错误但现在修复了）
        if os.path.exists(LAST_ALERT_FILE):
            try:
                os.remove(LAST_ALERT_FILE)
                logging.info("已清除之前的告警记录")
            except Exception as e:
                logging.warning(f"清除告警记录失败: {e}")
