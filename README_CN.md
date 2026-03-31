# AIVane AI RPA

这是 `aivane.net` 上公开的 `aivanelabs/ai-rpa` 项目仓，对外展示 AIVane（AI Mobile Automation）Android REPL beta 线。

## 快速开始

1. 确保 Android 设备安装了 AIVane REPL beta APK，且与电脑在同一 Wi-Fi 网络。
2. 运行客户端：  
   ```bash
   python clients/python/aria_tree.py --repl --url http://<device-ip>:8080
   ```
3. 在 REPL 中保存地址（`set url http://<device-ip>:8080`），接着执行 smoke 流：`health`、`apps`、`la <package>`、`list`、`tap <refId>`、`input <refId>`、`back`、`press home`、`screenshot`（如已授权）。

## 公开资料

- `clients/python/aria_tree.py`：REPL 客户端，调用 `/api/execute`、`/health`、`/screenshot`、`/api/apps`。
- `docs/`：包含 quickstart、协议说明、权限说明、known limitations、反馈、release notes、repo scope。
- `examples/`：提供 smoke 流、操作矩阵和启动脚本示例。
- `skills/android-repl/`：公开技能定义、提示词和 agents 元数据。

## 安装与启动

- `docs/install-android-repl.md`：指导 APK 安装、同局域网、首次 smoke。
- `examples/start-app-repl.sh`：公开版启动脚本示例，用于在设备上打开 `aivane.apprepl`。

## 附加资源

- `docs/agent-examples.md`：针对 Codex / Claude Code / OpenClaw 的最简提示。
- `.github/ISSUE_TEMPLATE/`：bug/feature 报告模板，帮助收集可操作信息。

## 已知限制

详见 `docs/known-limitations.md`（权限弹窗、仅限 LAN 等 Beta 限制）。

## 联系方式

如需讨论/协作，请发邮件至 `aivanelabs@gmail.com`。
