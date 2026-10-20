#!/usr/bin/env python3
"""把列表页切到分页接口（一次性脚本，幂等）。

只处理"列表 + 表格"结构的页面：策略组、分流规则、节点来源、规则来源、
引擎平台、设备管理、功能模块、构建发布。
"""
import re
from pathlib import Path

PAGES = {
    "src/views/Rules.vue": {
        "path": "/api/v1/rules/page",
        "assign": "rules",
    },
    "src/views/Sources.vue": {
        "path": "/api/v1/sources/page",
        "assign": "sources",
    },
    "src/views/RuleProviders.vue": {
        "path": "/api/v1/rule-providers/page",
        "assign": "providers",
    },
    "src/views/Targets.vue": {
        "path": "/api/v1/targets/page",
        "assign": "targets",
    },
    "src/views/Devices.vue": {
        "path": "/api/v1/devices/page",
        "assign": "devices",
    },
    "src/views/Snippets.vue": {
        "path": "/api/v1/snippets/page",
        "assign": "snippets",
    },
    "src/views/Builds.vue": {
        "path": "/api/v1/builds/page",
        "assign": "builds",
    },
}


def add_state(s: str) -> str:
    if "const total = ref(0)" in s:
        return s
    s = s.replace("const rows = ref([])",
                  "const rows = ref([])\nconst total = ref(0)\n"
                  "const page = ref(1)\nconst limit = ref(50)", 1)
    return s


def add_import(s: str) -> str:
    if "components/Pager.vue" in s:
        return s
    if "import EmptyState from '../components/EmptyState.vue'" in s:
        return s.replace("import EmptyState from '../components/EmptyState.vue'",
                         "import EmptyState from '../components/EmptyState.vue'\n"
                         "import Pager from '../components/Pager.vue'", 1)
    return s.replace("import { api } from '../api'",
                     "import { api } from '../api'\n"
                     "import Pager from '../components/Pager.vue'", 1)


def add_handler(s: str) -> str:
    if "function onPageChange" in s:
        return s
    return s.replace("async function load() {",
                      "function onPageChange({ page: p, limit: l }) {\n"
                      "  page.value = p\n"
                      "  limit.value = l\n"
                      "  load()\n"
                      "}\n\n"
                      "async function load() {", 1)


def add_pager(s: str) -> str:
    if "<Pager" in s:
        return s
    # 表格所在的卡片：</el-table> 之后、</div> 之前
    m = re.search(r"(\n(\s*)</el-table>\n\s*</div>\n)", s)
    if not m:
        return s
    indent = m.group(2)
    pager = (f"{indent[:-2]}<Pager :page=\"page\" :limit=\"limit\" :total=\"total\" "
             "@change=\"onPageChange\" />\n")
    return s[:m.end(1)] + pager + s[m.end(1):]


def rewire(s: str, path: str, assign: str) -> str:
    """把 rows.value = <x> 换成分页请求。"""
    if f"{path}?limit=" in s:
        return s
    # 1) 找到赋值 rows.value = X 的位置，替换为分页请求
    m = re.search(r"^(\s*)rows\.value = (\w+)\s*$", s, re.M)
    if not m:
        return s
    indent, var = m.group(1), m.group(2)
    new = (f"{indent}const paged = await api(`{path}?limit=${{limit.value}}"
           f"&offset=${{(page.value - 1) * limit.value}}`)\n"
           f"{indent}rows.value = paged.items\n"
           f"{indent}total.value = paged.total")
    s = s[:m.start()] + new + s[m.end():]
    # 2) 原来的那个变量改名为 pagedData（如果它就是分页数据源）
    s = s.replace(f"const {var} = await api(", f"const {var}Data = await api(", 1)
    return s


def main() -> None:
    for name, cfg in PAGES.items():
        p = Path(name)
        s = p.read_text()
        s = add_state(s)
        s = add_import(s)
        s = add_handler(s)
        s = add_pager(s)
        s = rewire(s, cfg["path"], cfg["assign"])
        p.write_text(s)
        print("patched", name)


if __name__ == "__main__":
    main()
