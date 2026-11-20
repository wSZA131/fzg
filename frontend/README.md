# Frontend 文档

前端采用多页面 + 模块化脚本结构，页面入口在 `frontend/` 根目录，页面逻辑在 `frontend/assets/js/pages/`，共享能力在 `frontend/assets/js/shared/`。

## 页面索引

- `index.html`：主页入口。
- `chat.html`：智能体聊天页（默认自动路由到智能体与知识库，无需手动切换模式）。
- `dashboard.html`：学习与系统指标看板。
- `knowledge-map.html`：知识图谱可视化。
- `question-bank.html`：题库相关页面。
- `spaces.html`：学习空间资料管理。
- `test-report-dashboard.html`：测试/回归结果展示。

## 目录约定

- `assets/css/shared/`：跨页面复用样式。
- `assets/css/pages/`：页面私有样式。
- `assets/js/shared/`：用户上下文、API 工具、壳层逻辑。
- `assets/js/pages/`：页面业务逻辑。

## 移动端与 PWA

移动端不是独立入口，而是同一套页面的窄屏形态，避免维护两份 UI。

- **底部 Tab**：由 `assets/js/shared/page-shell.js` 读取侧边栏的 `[data-side-link]` 动态生成，
  导航文案与图标因此只有侧边栏这一处来源，新增页面无需改两遍。
- **样式**：`assets/css/shared/mobile-shell.css`，只在 `max-width: 760px` 生效，桌面端零影响；
  不含任何全局重置，不覆盖页面既有样式。
- **安全区**：各页面 `viewport` 已带 `viewport-fit=cover`，Tab 高度与 iPhone 底部 home 条通过
  `env(safe-area-inset-bottom)` 兼容。
- **应用清单**：`manifest.webmanifest` + `assets/images/app-icon-{192,512}.png`，
  支持“添加到主屏幕”后以独立窗口启动。
- **离线兜底**：`sw.js` 只缓存静态资源（`/api/` 请求完全绕过，不会读到过期业务数据），
  页面导航采用 network-first，断网时回落到 `offline.html`。
- **拍照上传**：沿用 `<input type="file" accept="image/*">`，移动端浏览器会自动提供
  “拍照 / 相册”选择，不额外设置 `capture`，以免强制开相机导致无法从相册选题。

> Service Worker 仅在 HTTPS 或 localhost 下注册，HTTP 部署时静默跳过，不影响其他功能。

## 朗读与检索

- **朗读 / 听讲解**：`assets/js/shared/speech-player.js`，基于浏览器原生 `SpeechSynthesis`，
  不依赖任何云 TTS，学习内容不出本机。文本会先清理 Markdown、代码块与公式，再按句子分段播放；
  浏览器不支持该 API 时不渲染入口按钮。

  已接入三处，共用 `assets/css/shared/speech.css` 与同一套 DOM 约定：

  | 入口 | 取值方式 |
  | --- | --- |
  | 问答消息 | 默认读取同一条消息的 `.message-text` |
  | 空间资料预览 | `data-speak-source="#spaceReaderBody"`（音视频与图片类型自动隐藏） |
  | 知识点详情 | `data-speak-text`，由 `knowledge-map.js` 在选中节点时写入 |

  接入方式：按钮加 `data-speak-toggle`，并按需补 `data-speak-text` 或 `data-speak-source`；
  按钮内部需保留 `.message-action-icon` 与 `.message-action-label`，脚本靠这两个类切换播放状态。
- **空间内搜索**：顶栏搜索按钮打开面板，调用 `GET /api/spaces/search`，
  跨空间匹配标题、摘要与正文；点击结果跳转到对应空间并定位到该资料。

## 主题与语言

- **主题**：`assets/js/shared/auth-ui.js` 的 `applyPreferences()` 把偏好写到
  `<html data-fangzhigong-theme="light|dark">`，样式覆盖集中在 `assets/css/shared/auth-ui.css` 末尾。
  各页面存在大量内联硬编码颜色，因此深色模式用属性选择器 + `!important` 统一覆盖主要容器、
  文字与表单控件；插画与渐变图片仍沿用浅色资源。
  为避免首屏闪白，7 个页面 `<head>` 内各有一小段内联脚本，在渲染前读取偏好并打上属性。
- **语言**：`assets/js/shared/i18n.js` 维护「中文原文 → 英文」映射，在页面加载后对框架区域
  （登录/注册弹窗、找回密码、账号设置、用户菜单、侧边栏、底部导航、空间搜索面板）做文本替换，
  并监听动态插入的节点。
  采用映射而非改写各处模板字符串：现有 UI 由大量模板拼接而成，逐处替换容易漏且改动面大。
  页面正文（AI 回答、资料内容）不参与替换，避免误伤学习材料。
  切换语言后整页重载，中文模式下不做任何处理。

## 与后端通信约定

- 普通接口：`fetch + JSON`。
- 多模态上传：`FormData`（图片文件 + 文本字段）。
- 智能体流式：SSE（`text/event-stream`），用于展示中间步骤与工具调用反馈。

## 智能体页面行为（chat）

- 文本问题默认发送到 `/api/agent/ocr-tutor`，由后端自动决定是否调用知识库、图谱与其他工具。
- 当智能体通道异常时，前端会自动回退到 `/api/ask`，避免要求用户手动切换模式。
- 图片优先走 OCR；OCR 失败但有文本时，后端会自动降级到文本路径。
- 支持展示 `steps_log` 工作流时间线与证据信息。

## 前端版本时间线（倒序）

### 2026-11-18（当前）

- 移动端适配：底部 Tab 导航（复用侧边栏导航数据）、安全区适配、输入框聚焦自动收起 Tab。
- 新增 PWA：`manifest.webmanifest`、应用图标、`offline.html` 与 `sw.js`（只缓存静态资源，API 请求完全绕过）。
- 全站 `viewport` 补 `viewport-fit=cover`，修复 `dashboard.html` 缺失 viewport 的问题。
- `deploy/nginx.conf` 为 `/sw.js`、`/manifest.webmanifest` 关闭长缓存。

### 2026-04-10

- 对齐智能体流式路径与后端契约。
- 强化智能体工作流展示与错误降级体验。

### 2026-04（上旬）

- 聊天页收起手动模式开关，默认自动智能体路由并保留工具轨迹展示。
- 新增测试报告看板、知识图谱页和学习空间页增强。

### 2026-03（历史）

- 多页面布局与基础共享模块建立。

## 开发建议

- 新增页面时，HTML 放 `frontend/` 根目录，逻辑放 `assets/js/pages/`。
- 跨页面复用能力统一收敛到 `assets/js/shared/`。
- 避免新增泛名文件（如 `main.js`、`style.css`），优先按页面命名。
