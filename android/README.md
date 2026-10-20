# MagicPanel 安卓客户端

管理端的 Android 原壳（Kotlin + WebView）。管理端本身是 Web 应用，
App 负责承载它：登录态持久化、文件上传、下载、深色主题、返回键行为。

## 产物

- `app/build/outputs/apk/release/app-release.apk` —— 已签名，可直接安装
- `dist/MagicPanel-1.0.1.apk` —— 发布版（versionCode 2）

## 版本记录

| 版本 | 改动 |
|---|---|
| 1.0.1 | 去掉下拉刷新容器（向下滑动不再被刷新手势劫持，刷新改为工具栏按钮）；修复加载指示一直转圈不消失（页面结束/出错/15 秒看门狗三条路径都会收起）；新增右下角可拖动悬浮小房子，点击回门户首页，松开自动吸附到左右边缘并记住位置；悬浮按钮改为深色底 + 品牌蓝图标，与深色主题协调，默认落在右下角 |
| 1.0.0 | 首个版本 |

## 面板地址

默认 `https://magichub.top:8443`。App 内「⋮ → 面板地址」可改，改完立即生效
（存 SharedPreferences，不依赖重新打包）。

## 签名

| 项 | 值 |
|---|---|
| keystore | `app/magicpanel.keystore`（**不入库**，需要自行备份） |
| 别名 / 口令 | `magicpanel` / `magicpanel` |
| 备份位置 | 本机 `~/tools/keystore-backup/magicpanel.keystore` |

> 换机器或密钥丢失后重新签名的 APK **无法覆盖安装**旧版本（签名不一致），
> 需要先卸载再装。

## 构建

```bash
export JAVA_HOME=~/tools/jdk21/Contents/Home
export ANDROID_HOME=~/tools/android-sdk
export PATH=$JAVA_HOME/bin:$HOME/tools/gradle-8.9/bin:$PATH
cd android
gradle --no-daemon assembleRelease
```

产物：`app/build/outputs/apk/release/app-release.apk`

## 适配

- minSdk 24（Android 7.0）/ targetSdk 35（Android 15）
- 已适配 Android 15+ 强制 edge-to-edge（状态栏与手势条内边距）
- 覆盖小米 17 Pro Max、一加 13 等主流 Android 15/16 机型
- 只允许 HTTPS，面板域名走 `magichub.top:8443`
