#!/usr/bin/env python3
import pathlib
import json
import re
import sys
import time
import urllib.request


BASE_URL = "https://list.magichub.top/d/clash/rules"
RULE_SOURCES_FILE = "rule_sources.json"

RULE_SOURCES = {
    "reject.txt": "https://raw.githubusercontent.com/Loyalsoldier/clash-rules/release/reject.txt",
    "lan.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Lan/Lan.yaml",
    "chatgpt.list": "https://raw.githubusercontent.com/cutethotw/ClashRule/main/Rule/ChatGPT.list",
    "perplexity.list": "https://raw.githubusercontent.com/cutethotw/ClashRule/main/Rule/Perplexity.list",
    "grok.list": "https://raw.githubusercontent.com/cutethotw/ClashRule/main/Rule/Grok.list",
    "claude.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Claude/Claude.yaml",
    "openai.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/OpenAI/OpenAI.yaml",
    "anthropic.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Anthropic/Anthropic.yaml",
    "gemini.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Gemini/Gemini.yaml",
    "copilot.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Copilot/Copilot.yaml",
    "github.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/GitHub/GitHub.yaml",
    "jetbrains.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Jetbrains/Jetbrains.yaml",
    "twitter.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Twitter/Twitter.yaml",
    "facebook.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Facebook/Facebook.yaml",
    "instagram.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Instagram/Instagram.yaml",
    "telegram.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Telegram/Telegram.yaml",
    "discord.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Discord/Discord.yaml",
    "whatsapp.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Whatsapp/Whatsapp.yaml",
    "reddit.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Reddit/Reddit.yaml",
    "linkedin.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/LinkedIn/LinkedIn.yaml",
    "line.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Line/Line.yaml",
    "youtube.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/YouTube/YouTube.yaml",
    "google.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Google/Google.yaml",
    "netflix.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Netflix/Netflix.yaml",
    "disney.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Disney/Disney.yaml",
    "hbo.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/HBO/HBO.yaml",
    "hboasia.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/HBOAsia/HBOAsia.yaml",
    "spotify.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Spotify/Spotify.yaml",
    "tiktok.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/TikTok/TikTok.yaml",
    "twitch.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Twitch/Twitch.yaml",
    "primevideo.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/PrimeVideo/PrimeVideo.yaml",
    "wikipedia.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Wikipedia/Wikipedia.yaml",
    "bahamut.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Bahamut/Bahamut.yaml",
    "tvb.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/TVB/TVB.yaml",
    "playstation.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/PlayStation/PlayStation.yaml",
    "xbox.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Xbox/Xbox.yaml",
    "nintendo.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Nintendo/Nintendo.yaml",
    "microsoft.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Microsoft/Microsoft.yaml",
    "onedrive.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/OneDrive/OneDrive.yaml",
    "appleproxy.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AppleProxy/AppleProxy.yaml",
    "apple.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Apple/Apple.yaml",
    "paypal.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/PayPal/PayPal.yaml",
    "bilibili.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/BiliBili/BiliBili.yaml",
    "iqiyi.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/iQIYI/iQIYI.yaml",
    "youku.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Youku/Youku.yaml",
    "tencent.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Tencent/Tencent.yaml",
    "privatetracker.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/PrivateTracker/PrivateTracker.yaml",
    "proxy-all.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Proxy/Proxy.yaml",
    "proxy-domain.txt": "https://raw.githubusercontent.com/Loyalsoldier/clash-rules/release/proxy.txt",
    "china.yaml": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/China/China.yaml",
    "direct.txt": "https://raw.githubusercontent.com/Loyalsoldier/clash-rules/release/direct.txt",
}


def repo_root():
    return pathlib.Path(__file__).resolve().parents[2]


def load_rule_sources():
    sources_path = pathlib.Path(__file__).resolve().with_name(RULE_SOURCES_FILE)
    if not sources_path.is_file():
        return RULE_SOURCES

    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    if not isinstance(sources, dict) or not sources:
        raise RuntimeError(f"{sources_path} must contain a non-empty object")

    for filename, source_url in sources.items():
        if not isinstance(filename, str) or not isinstance(source_url, str):
            raise RuntimeError(f"{sources_path} entries must be string pairs")
        if "github.com" not in source_url and "raw.githubusercontent.com" not in source_url:
            raise RuntimeError(f"{filename} source is not a GitHub URL: {source_url}")

    return sources


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "MagicHub/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
        status = getattr(response, "status", 200)
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        if not data.strip():
            raise RuntimeError("downloaded empty content")
        return data


def ensure_config_urls(config_path):
    text = config_path.read_text(encoding="utf-8")
    updated = text
    missing = []

    for filename in load_rule_sources():
        stem = filename.rsplit(".", 1)[0]
        provider_name = "proxy-all" if filename == "proxy-all.yaml" else stem
        expected_url = f"{BASE_URL}/{filename}"
        block_pattern = re.compile(
            rf"(?ms)^(  {re.escape(provider_name)}:\n)(.*?)(?=^  [^\s].*?:\n|^rules:\n|\Z)"
        )
        match = block_pattern.search(updated)
        if not match:
            missing.append(provider_name)
            continue

        block = match.group(0)
        new_block, count = re.subn(
            r"(?m)^    url: .*$",
            f"    url: '{expected_url}'",
            block,
            count=1,
        )
        if count != 1:
            missing.append(provider_name)
            continue
        updated = updated[: match.start()] + new_block + updated[match.end() :]

    if missing:
        raise RuntimeError("missing provider blocks: " + ", ".join(missing))
    if updated != text:
        config_path.write_text(updated, encoding="utf-8", newline="")


def main():
    root = repo_root()
    rules_dir = root / "clash" / "rules"
    config_path = root / "clash" / "config.yaml"
    rules_dir.mkdir(parents=True, exist_ok=True)

    rule_sources = load_rule_sources()
    failures = []
    for filename, source_url in rule_sources.items():
        candidates = [source_url, "https://ghfast.top/" + source_url]
        content = None
        errors = []
        for candidate in candidates:
            try:
                content = download(candidate)
                break
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
                time.sleep(0.1)
        if content is None:
            failures.append((filename, errors))
            continue
        (rules_dir / filename).write_bytes(content)
        print(f"updated {filename} ({len(content)} bytes)")

    if failures:
        for filename, errors in failures:
            print(f"FAILED {filename}", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
        return 1

    ensure_config_urls(config_path)
    print(f"updated {len(rule_sources)} GitHub rule sets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
