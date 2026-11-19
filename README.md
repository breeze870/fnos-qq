# 飞牛 QQ

在 x86-64 飞牛 NAS 上运行腾讯 Linux QQ，从飞牛桌面打开，点击左侧账号图标切换。应用以普通应用用户身份运行，每个账号使用独立的主目录、客户端数据目录与图形会话。

## 安装

1. 在 [Releases](https://github.com/breeze870/fnos-qq/releases) 下载 `.fpk`。同页的 `.sha256` 可用于校验文件。
2. 打开飞牛「应用中心 → 手动安装」，选择 FPK，启动「QQ」。
3. 首次打开时，选择腾讯提供的 **amd64 Debian 安装包**（单个文件最大 512 MiB），点击「开始安装」。文件可以来自电脑，也可以从电脑已挂载的 NAS 共享目录中选择。[腾讯 Linux QQ 下载页](https://im.qq.com/linuxqq/)
4. 用手机 QQ 扫码登录。点击「添加账号」可新建桌面，点击账号图标即可切换。「停止此桌面」会退出该桌面的 QQ 进程，保留账号数据。

FPK 提供图形会话和浏览器界面，QQ 客户端由用户单独提供。安装器校验 deb 的包名、架构和可执行文件，以应用用户权限解包原始客户端。各桌面共享同一个飞牛应用用户，适用于同一位 NAS 用户管理自己的账号。当前桌面入口限飞牛 UID 1000 使用。

## 兼容性

目标平台为 x86-64 fnOS，运行时基于 Debian 12 amd64 和系统 Python 3.11。应用自带 TigerVNC、aiohttp 和部分运行库，使用宿主机的 Python、dpkg-deb、xauth、mcookie、D-Bus、X11 和 GTK 等组件。启动时缺少必要工具会显示具体名称。安装包、账号数据和运行日志保存在本应用的 `TRIM_PKGVAR` 中。

正式包 ID 为 `fnos-qq`。从先前独立开发版本切换时，飞牛会将它作为新应用安装，需重新选择 deb 并登录。

## 构建

`package/` 包含飞牛应用工程，`scripts/runtime-lock.json` 固定 Debian 依赖的版本、来源和 SHA-256，`vendor/novnc/` 包含浏览器远程桌面客户端及其版权说明。依赖包中的版权文件会随 FPK 分发。各依赖的对应源码可按锁文件中的 `source` 和 `source_version` 在 [Debian Sources](https://sources.debian.org/) 或 [Debian Snapshot](https://snapshot.debian.org/) 查询。

在 Linux 或 macOS 上准备 Python 3.9+、`ar` 和飞牛官方 `fnpack 1.2.3`，在仓库根目录执行以下命令。[fnpack 文档](https://developer.fnnas.com/docs/cli/fnpack)

```sh
python3 scripts/build.py --fnpack /path/to/fnpack
```

产物写入 `dist/`。首次构建会下载并校验锁定的运行依赖，后续可复用本地缓存。构建全程无需 QQ 安装包。

## 发布

GitHub Actions 支持在 Actions 页面手动构建并下载产物。正式发布时，先更新 `package/manifest` 中的版本，提交到主分支，再推送同版本的标签，例如 `v0.1.0`。工作流会检查标签和清单版本是否一致，构建 amd64 FPK，并将安装包和 SHA-256 校验文件附加到对应的 GitHub Release。

QQ 名称、图标和客户端归腾讯所有。本项目由社区维护。
