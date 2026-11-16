#!/usr/bin/env python
"""本地 feed 冻结契约工具；只操作给定文件，不访问网络。"""
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / 'server') not in sys.path:
    sys.path.insert(0, str(ROOT / 'server'))

from app.services import feed_freeze  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    prepare = sub.add_parser('prepare', help='从私密 JSON 快照生成冻结目录')
    prepare.add_argument('--snapshot', required=True)
    prepare.add_argument('--root', required=True)

    verify = sub.add_parser('verify', help='校验已 arm 快照')
    verify.add_argument('--root', required=True)

    arm = sub.add_parser('arm', help='核对全部字节后原子切换 ACTIVE')
    arm.add_argument('--root', required=True)
    arm.add_argument('--expected-sha', required=True)

    release = sub.add_parser('release', help='按最终回执撤保护')
    release.add_argument('--root', required=True)
    release.add_argument('--expected-sha', required=True)
    release.add_argument('--receipt', required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == 'prepare':
        raw = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
        routes = []
        for route in raw.get('routes', []):
            routes.append({**route, 'body': base64.b64decode(route['body_base64'], validate=True)})
        result = feed_freeze.prepare_freeze({'routes': routes}, destination=Path(args.root))
    elif args.command == 'verify':
        result = feed_freeze.verify_freeze(Path(args.root))
    elif args.command == 'arm':
        result = feed_freeze.arm_freeze(Path(args.root), expected_sha=args.expected_sha)
    elif args.command == 'release':
        receipt = json.loads(Path(args.receipt).read_text(encoding='utf-8'))
        result = feed_freeze.release_freeze(Path(args.root), expected_sha=args.expected_sha,
                                            receipt=receipt)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
