import socket
import requests
import time

# 在這裡放入你需要檢查的域名列表
DOMAINS = [
    "github.com",
    "github.io",
    "githubapp.com",
    "githubassets.com",
    "githubusercontent.com",
    "copilot-proxy.githubusercontent.com",
    "ghcr.io",
    "pkg.github.com",
    "github.global.ssl.fastly.net",
    "docker.com",
    "docker.io",
    "hub.docker.com",
    "production.cloudflare.docker.com",
    "gcr.io",
    "k8s.gcr.io",
    "registry.k8s.io",
    "quay.io",
    "redhat.com",
    "redhat.io",
    "npmjs.com",
    "npmjs.org",
    "npm.community",
    "yarnpkg.com",
    "pnpm.io",
    "electronjs.org",
    "cypress.io",
    "pypi.org",
    "python.org",
    "pythonhosted.org",
    "go.dev",
    "golang.org",
    "sum.golang.org",
    "proxy.golang.org",
    "googlesource.com",
    "rust-lang.org",
    "crates.io",
    "static.crates.io",
    "index.crates.io",
    "maven.org",
    "apache.org",
    "gradle.org",
    "gradle-dn.com",
    "spring.io",
    "sonatype.org",
    "packagist.org",
    "composer.org",
    "rubygems.org",
    "brew.sh",
    "bintray.com",
    "ubuntu.com",
    "canonical.com",
    "launchpad.net",
    "centos.org",
    "fedoraproject.org",
    "debian.org",
    "debian.net",
    "archlinux.org",
    "alpinelinux.org",
    "s3.amazonaws.com",
    "storage.googleapis.com",
    "blob.core.windows.net",
    "stackoverflow.com",
    "sstatic.net",
]


def get_ip_location(domain):
    try:
        # 1. DNS 解析：獲取 IP
        ip = socket.gethostbyname(domain)
    except socket.gaierror:
        return {"domain": domain, "ip": "解析失敗", "location": "未知", "type": "未知"}

    try:
        # 2. IP 歸屬地查詢 (使用 ip-api.com，lang=zh-CN 請求中文結果)
        # 注意：這個免費接口限制每分鐘 45 次請求，批量大時需注意延遲
        response = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=5)
        data = response.json()

        if data["status"] == "success":
            country = data["country"]
            region = data["regionName"]
            city = data["city"]
            country_code = data["countryCode"]

            # 組合詳細地址，例如：中國 河北 保定
            full_location = f"{country} {region} {city}"

            # 3. 判斷國內/國外
            # CN 代表中國大陸，HK/TW/MO 通常被視為境外節點（根據你的需求調整）
            if country_code == "CN":
                location_type = "🟢 國內"
            else:
                location_type = "🔴 國外"

            return {
                "domain": domain,
                "ip": ip,
                "location": full_location,
                "type": location_type,
            }
        else:
            return {"domain": domain, "ip": ip, "location": "查詢失敗", "type": "未知"}

    except Exception as e:
        return {
            "domain": domain,
            "ip": ip,
            "location": f"API錯誤: {str(e)}",
            "type": "未知",
        }


def main():
    print(f"{'域名':<20} | {'IP地址':<16} | {'類型':<6} | {'詳細位置'}")
    print("-" * 70)

    for domain in DOMAINS:
        result = get_ip_location(domain)
        print(
            f"{result['domain']:<20} | {result['ip']:<16} | {result['type']:<6} | {result['location']}"
        )

        # 避免觸發 API 頻率限制 (免費版限制每分鐘 45 次)
        time.sleep(1)


if __name__ == "__main__":
    main()
