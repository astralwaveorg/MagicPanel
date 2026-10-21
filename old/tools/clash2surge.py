#!/usr/bin/env python3
"""
Clash YAML to Surge INI converter
"""

import sys
import yaml
import json
from datetime import datetime

def convert_clash_to_surge(clash_data):
    """Convert Clash proxy list to Surge INI format"""
    lines = []
    lines.append("# MagicHub 节点检测结果")
    lines.append(f"# 生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("")

    proxies = clash_data.get('proxies', [])
    lines.append(f"# 总节点数: {len(proxies)}")
    lines.append("")

    for proxy in proxies:
        name = proxy.get('name', 'Unnamed')
        ptype = proxy.get('type', '')

        if ptype == 'ss':
            server = proxy.get('server', '')
            port = proxy.get('port', '')
            cipher = proxy.get('cipher', 'aes-256-gcm')
            password = proxy.get('password', '')
            plugin = proxy.get('plugin', '')

            if plugin == 'obfs':
                plugin_opts = proxy.get('plugin-opts', {})
                obfs = plugin_opts.get('mode', 'http')
                obfs_host = plugin_opts.get('host', '')
                line = f'{name} = ss, {server}, {port}, encrypt-method={cipher}, password={password}, obfs={obfs}, obfs-host={obfs_host}'
            elif plugin == 'v2ray-plugin':
                plugin_opts = proxy.get('plugin-opts', {})
                line = f'{name} = ss, {server}, {port}, encrypt-method={cipher}, password={password}, plugin=v2ray-plugin'
            elif plugin == 'shadow-tls':
                plugin_opts = proxy.get('plugin-opts', {})
                host = plugin_opts.get('host', '')
                version = plugin_opts.get('version', '2')
                skip_cert = plugin_opts.get('skip-cert-verify', False)
                plugin_password = plugin_opts.get('password', '')
                line = f'{name} = ss, {server}, {port}, encrypt-method={cipher}, password={password}, plugin=shadow-tls, plugin-opts=host={host},version={version},skip-cert-verify={str(skip_cert).lower()},password={plugin_password}'
            else:
                line = f'{name} = ss, {server}, {port}, encrypt-method={cipher}, password={password}'

        elif ptype == 'vless':
            server = proxy.get('server', '')
            port = proxy.get('port', '')
            uuid = proxy.get('uuid', '')
            tls = 'true' if proxy.get('tls', False) else 'false'
            flow = proxy.get('flow', '')
            network = proxy.get('network', 'tcp')

            extra = []
            if tls:
                extra.append('tls')
            if flow:
                extra.append(f'flow={flow}')
            if network != 'tcp':
                extra.append(f'type={network}')

            if extra:
                line = f'{name} = vless, {server}, {port}, username={uuid}, {", ".join(extra)}'
            else:
                line = f'{name} = vless, {server}, {port}, username={uuid}, tls'

        elif ptype == 'vmess':
            server = proxy.get('server', '')
            port = proxy.get('port', '')
            uuid = proxy.get('uuid', '')
            alterId = proxy.get('alterId', 0)
            cipher = proxy.get('cipher', 'auto')
            tls = 'true' if proxy.get('tls', False) else 'false'
            network = proxy.get('network', 'tcp')

            if network == 'tcp':
                line = f'{name} = vmess, {server}, {port}, username={uuid}, tls={tls}'
            else:
                line = f'{name} = vmess, {server}, {port}, username={uuid}, tls={tls}'

        elif ptype == 'trojan':
            server = proxy.get('server', '')
            port = proxy.get('port', '')
            password = proxy.get('password', '')
            sni = proxy.get('sni', server)
            skip_cert = proxy.get('skip-cert-verify', False)

            line = f'{name} = trojan, {server}, {port}, password={password}, sni={sni}, skip-cert-verify={str(skip_cert).lower()}'

        elif ptype == 'hysteria2' or ptype == 'hy2':
            server = proxy.get('server', '')
            port = proxy.get('port', '')
            password = proxy.get('password', '')
            sni = proxy.get('sni', server)
            skip_cert = proxy.get('skip-cert-verify', False)

            line = f'{name} = hysteria2, {server}, {port}, password={password}, sni={sni}, skip-cert-verify={str(skip_cert).lower()}'

        else:
            # Fallback for unknown types
            line = f'{name} = {ptype}, {proxy.get("server", "")}, {proxy.get("port", "")}'

        lines.append(line)

    return '\n'.join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: clash2surge.py <clash_yaml_file> [output_file]", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove comments and empty lines for parsing
    data = yaml.safe_load(content)

    if not data or 'proxies' not in data:
        print("Error: Invalid Clash YAML format", file=sys.stderr)
        sys.exit(1)

    surge_content = convert_clash_to_surge(data)

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(surge_content)
        print(f"Converted {len(data.get('proxies', []))} proxies to {output_file}")
    else:
        print(surge_content)


if __name__ == '__main__':
    main()
