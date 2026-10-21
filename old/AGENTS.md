# Repository Guidelines

## Network Context & Mandatory Constraints

Status as of 2026-10-19: **household migration remains design/review only**. User explicitly authorized local MacBook cleanup, now completed: Stash 4.4.0 retained; other proxy apps/core/helpers removed; old Surge extension terminated, pending OS removal on reboot. Do not reboot automatically. SSH inspection is authorized. Do not infer permission to stop services, deploy, reboot, or remediate from inspection access. Later explicit implementation requests authorize work within their scope without repeated permission questions.

| Device | Access / current state |
| --- | --- |
| NanoPi R6S | `root@10.0.1.1`; ImmortalWrt 24.10.4; basic router; installed Nikki is not running |
| Mac mini M4 | `nora@10.0.1.8`; macOS; headless, wired gigabit; **Surge is a normal production service used by the NAS** |
| fnOS NAS | `archon@10.0.1.2`; Debian 12; Xeon E-2176G, 6C12T, 32 GB; wired gigabit; uses mini proxy |
| MacBook M2 Pro | This computer; **Stash 4.4.0 running**, Stash Dashboard retained; ClashBar/Surge/Mihomo removed; Stash network extension enabled |

Other devices: iPhone 17 Pro Max, Xiaomi 17 Pro Max (HyperOS 4), ordered Apple TV 4K (user-reported 2026/A19), Lenovo R9000K 2021 (Ryzen 9 5900HX, Windows). LAN: `10.0.1.0/24`; WAN understood as 100 Mbps up / 1000 Mbps down.

- R6S must not run proxy services. Do not change gateways, DHCP, base DNS, WAN forwarding, or existing Nikki for this proxy plan; router findings await review.
- Devices manually opt into mini HTTP/SOCKS proxy; independent clients serve travel/full-device needs. No transparent gateway or LAN DNS takeover. Unproxied devices must remain independent of mini/NAS availability.
- Preserve working Surge and NAS consumers. Planned Stash migration/ports are not live services. Empty SSH proxy variables do not disprove application/container/daemon proxy use. Failed manual proxies may require disabling; never promise universal coverage or automatic direct fallback.

User confirmed **Stash Mac purchased; Windows + both Macs will use Stash**. iOS purchase also covers tvOS. Do not infer installed/activated/migrated status. Android recommendation remains FlClash, with Stash early access for evaluation. Windows Stash is also early; validate it separately. Keep Surge until mini Stash passes headless restart, LAN proxy and NAS acceptance. Independent Mihomo/CVR are fallback designs, not the current desktop target.

Remote full-profile HTTPS feeds are the authority, **not Stash iCloud sync**. Use one policy source with platform-specific outputs; never assume shared YAML means feature parity. Cloud control-plane design is not implemented. Read [client compatibility](docs/network/Client-Selection-and-Compatibility.md) and [console specification](docs/development/Remote-Config-Console.md) only when relevant.

Read [dated device context](docs/network/Network-Operations-Context.md), then only relevant [architecture](docs/network/Home-Proxy-Architecture.md), [migration/rollback](docs/network/Mac-mini-LAN-Proxy-Plan.md), or [router audit](docs/network/audits/R6S-Security-Stability-Review.md). Recheck affected facts before operations; update status after real changes.

## Project Structure & Development Commands

- `clash/`: YAML, `rules/`, conversion `templates/`, platform files in `mihomo/` and `box4magisk/`.
- `surge/`: device configurations, `nodes/`, `modules/`, generated routing lists; sources in `surge/rules/rules.yaml`.
- `bin/`, `clash/bin/`, `tools/`: maintenance/conversion; `icons/`, `static/`, `surge/assets/`: assets; `m3u/`: playlists; `external/subs-check/`: submodule.
- `docs/network/`: decisions/context; `audits/`: evidence; `docs/development/`: proposed console; `docs/reference/`: official navigation/index.

No application build/server or automated test framework is configured. From the root:

- `python3 -m pip install -r requirements.txt`: install pinned dependencies in a virtual environment.
- `python3 bin/update_rules.py`: download/regenerate Surge rules; overwrites outputs.
- `python3 tools/clash2surge.py <input.yaml> /tmp/output.ini`: inspect proxy conversion.
- `git diff --check`: whitespace check.

## Style, Validation & Contributions

Python: four spaces, `snake_case`, uppercase constants. Clash YAML generally uses two spaces. Preserve surrounding quoting, Surge sections, rule ordering, and lowercase service filenames. No formatter, coverage threshold, or linter is configured.

Validate YAML, inspect generated diffs, and check the intended client/core; parsing alone proves no runtime behavior. Converter changes need sanitized fixtures. Record checks and limitations in PRs.

Use specific action-oriented subjects; history includes `Update Clash subscription nodes` and `[Auto]SyncFiles`. PRs describe affected targets, linked issues and validation; asset changes include screenshots. Pushes to `main` trigger deployment. Keep credentials out of commits; maintenance scripts may force-push or send notifications. Ignore local caches/scratch output, not maintained docs/tools.

## Mandatory Official Documentation Check

Before editing configuration, templates, overrides, rule formats, or generators, identify client/core version/platform and consult relevant official original documentation: Mihomo `wiki.metacubex.one`, Stash `stash.wiki`, Surge `manual.nssurge.com`, plus tool/platform docs when applicable. Never assume dialects interchangeable or rely solely on memory, snippets, existing configs, or local summaries.

Start with `python3 scripts/docs_lookup.py search '<field>' --product mihomo` (or `stash`), then `read <official-url> --section '<heading>'`. Verify relevant pages online once per task; reuse validated cache afterward. Read prerequisites, examples, deprecations and version restrictions. Expand truncated excerpts. If compatibility cannot be verified, stop only the affected edit and report missing evidence.

Follow [the official-docs workflow](docs/reference/Official-Docs-Workflow.md). Use target parser/client checks where available; report exact official URLs, compatibility assumptions, and validations. Search metadata and read bounded sections instead of loading entire documentation caches.
