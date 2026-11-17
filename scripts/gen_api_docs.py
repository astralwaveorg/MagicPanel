#!/usr/bin/env python3
"""生成接口清单文档（杜绝手维护腐烂——此前 122/120/96 三处数字互相矛盾）。

用法：python3 scripts/gen_api_docs.py [--check]
  默认写 docs/development/接口清单与安卓客户端说明.md 的接口清单段；
  --check 只比对内容是否最新（CI/提交前用），不一致退出 1。
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

MARK = "<!-- 由 scripts/gen_api_docs.py 生成，勿手改 -->"


def collect() -> list[str]:
    # 临时数据目录：生成清单不需要真实数据，干净的初始化避免
    # 主密钥缺失时的降级日志噪音
    import tempfile
    os.environ.setdefault("MP_DATA_DIR", tempfile.mkdtemp())
    from app.main import create_app  # noqa: E402  依赖项目内环境
    app = create_app()
    lines = [MARK, "", f"共 {len(app.routes)} 条注册路由（含多方法合并）。", ""]
    current_module = ""
    from fastapi.routing import APIRoute
    api_routes = [r for r in app.routes if isinstance(r, APIRoute)]
    for route in sorted(api_routes, key=lambda r: (r.endpoint.__module__, r.path)):
        module = getattr(route.endpoint, "__module__", "")
        name = getattr(module, "__name__", "")
        if name != current_module:
            current_module = name
            lines += [f"## {name.split('.')[-1]}", ""]
        methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
        doc = (route.endpoint.__doc__ or "").strip().splitlines()[0]
        lines.append(f"- `{methods} {route.path}` {doc}")
    if lines[-1] != "":
        lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验不写入")
    args = parser.parse_args()
    doc_path = ROOT / "docs/development/接口清单与安卓客户端说明.md"
    old = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    start = old.find(MARK)
    generated = "\n".join(collect())
    if start == -1:
        new = old.rstrip() + "\n\n" + generated + "\n"
    else:
        new = old[:start] + generated
    if args.check:
        if old == new:
            print("接口清单已是最新")
            return 0
        print("接口清单过期：运行 python3 scripts/gen_api_docs.py 更新")
        return 1
    doc_path.write_text(new, encoding="utf-8")
    print(f"接口清单已生成：{doc_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
