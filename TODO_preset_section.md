# CcCompanion 配置方案切换 — 剩余工作

## 已完成
- 服务端 `/root/CcCompanion/apns-server/claude_presets.py` — preset 管理模块
- 服务端路由注册 (push.py): GET `/claude/presets`, POST `/claude/presets/apply`, POST `/claude/swap`
- 预设配置文件 `/root/.claude/presets/presets.json` (3 个方案: default/ds/minimax)
- SettingsView.swift 已插入 `ClaudePresetSection()` 引用 (在群聊 section 前面, line ~766)
- **SettingsView.swift 末尾写 `ClaudePresetSection` View 定义**
  - ViewModel: fetch `/claude/presets` 拿列表+当前 active
  - View: section("配置方案") 里渲染方案列表（radio 选中态）+ "立即 swap 重启" 按钮
  - 选方案 → POST `/claude/presets/apply` body `{"id": "xxx", "swap": true}`
  - 单独 swap 按钮 → POST `/claude/swap`
  - 风格参考同文件里 `TerminalSessionOrderView` 的简洁做法
- **审批卡片问题 (排查分析完成)**
  - 交互卡片（含有 Allow/Deny 按钮）由 iOS App 内部前台活跃时的长轮询 `/chat/poll` 自行渲染。
  - 当 App 退到后台或锁屏时，长轮询暂停，仅能接收到 APNs 服务器推送的纯文本 Alert（无交互按钮），需要重新点击进入 App 才会重新拉取并渲染出卡片。
  - iOS 对 silent push 限制较严，后台拉取唤醒在频繁触发时可能被系统限流挂起。

## 未完成
- 无。配置方案切换所有基本功能与卡片退化排查已全部处理完毕。

