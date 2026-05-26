# Changelog

## [v2.0] — 2026-05-26

> 集成版本，从核心对话升级为完整节点式工作流平台。

### 新增

**节点系统**
- 框选多节点：画布上拖拽框选，支持批量操作
- 多节点同步拖拽：一键移动整组节点，自动保持布局
- 右键菜单左键关闭：不需要精确点击关闭按钮，更顺手

**AI 交互**
- 图片拖拽/粘贴上传：从桌面直接拖入或从剪贴板粘贴
- 图片发送走 Hermes API vision 通道，自动调用视觉模型
- 文件上传（📎 按钮）：通用文件上传通道
- 助手激活反馈：点击节点后即时视觉反馈

**数字员工系统**（v1.0 已内置，v2.0 完善截图与展示）
- 多角色助手管理页面：工作流、技能库、助手配置、Workers、设置
- 节点式工作流编辑器：拖拽连线编排多步骤 AI 任务
- 技能库可视化面板
- Workers 状态监控面板

**项目规范**
- 新增 `CHANGELOG.md` 版本日志
- 新增 `v2.0` Git tag

### 变更

- 项目标题更新为「一个轻量化 HTML 文件的节点式工作流 AI 控制台」
- `.gitignore` 忽略 `.DS_Store`
- 截图全面更新，更准确反映当前界面

### 文件结构

```
hermes-chat/
├── hermes-chat.html          # 前端界面（~3070 行，~160KB）
├── hermes-chat-server.py     # 后端服务器（~600 行，~26KB）
├── CHANGELOG.md              # 本文件
├── README.md                 # 项目说明
├── LICENSE                   # MIT 许可
├── start.sh                  # 启动脚本
├── screenshots/              # 功能截图（6 张）
└── .gitignore
```

### 快速启动

```bash
cd ~/hermes-chat
PORT=8090 python3 hermes-chat-server.py
```

浏览器打开 `http://localhost:8090`

---

## v1.0 — 2026-05-25

> 首发版本，Hermes Agent 的 Web GUI 原型。

### 新增

- 单文件 HTML 架构，零构建依赖
- ChatGPT 风格对话界面，流式响应
- 节点式工作流编辑器，支持多步骤并行执行
- 条件分支逻辑与撤销/重做
- 数字员工系统：基于 cron 调度的自动化工作流
- 5 个内置 AI 助手角色
- 中英文双语界面 + 自定义语言包
- Hermes API 完全兼容
- MIT 开源协议
- 启动脚本 `start.sh`

### 文件结构

```
hermes-chat/
├── hermes-chat.html          # 前端界面（~2893 行）
├── hermes-chat-server.py     # 后端服务器（~583 行）
├── README.md                 # 项目说明
├── LICENSE                   # MIT 许可
├── start.sh                  # 启动脚本
└── .gitignore
```

### 快速启动

```bash
cd ~/hermes-chat
python3 hermes-chat-server.py
```

浏览器打开 `http://localhost:8090`
