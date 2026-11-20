# 华为云码道 CodeArts 代码智能体使用指南

> 赛题要求「下载并使用华为云码道 CodeArts 代码智能体」为**必选**项。
> 本文件记录本项目实际使用它的方式，同时作为参赛材料「开发过程」章节的素材清单。
>
> 注意：官方界面与菜单名称可能随版本变化，具体路径请以码道内实际显示为准；
> 本文命令与技能名来自公开文档与实践案例，**执行前请自行核对**。

## 一、它是什么

- **形态**：AI IDE 独立客户端，或 IDE 插件。使用华为云账号登录后，在侧边栏出现智能体对话面板。
- **计费**：提供免费体验版（赛题给的是专属开通入口）。
- **Skills**：技能以目录形式存在，入口文件是 `SKILL.md`，放在 `~/.codeartsdoer/skills/`（用户级）
  或项目下 `.codeartsdoer/skills/`（项目级）。
- **官方技能库**：`huaweicloud/huaweicloud-skills`，覆盖计算、数据库、存储、容器、安全等，
  通过自然语言即可调用华为云 API 完成资源开通与运维。

## 二、开通与安装

1. 通过赛题专属入口开通体验版（需华为云账号完成实名认证）：
   `https://developer.huaweicloud.com/codeartsco.html?source=dmzntcompetition`
2. 下载对应平台的客户端或插件并安装。
3. 用华为云账号登录，确认侧边栏出现智能体对话面板。
4. 首次使用建议先打开本仓库（而不是新建空项目），便于让智能体理解上下文。

## 三、安装 Skills

### 方式一：命令行安装（推荐）

```bash
# 安装 RDS 相关技能
npx skills add huaweicloud/huaweicloud-skills --skill huawei-rds

# 安装"查找技能"技能，可用自然语言发现其它技能
npx skills add huaweicloud/huaweicloud-skills --skill huawei-cloud-find-skills
```

GitCode 镜像源（国内网络更稳）：

```bash
npx skills add https://gitcode.com/huaweicloud/huaweicloud-skills.git --skill huawei-rds -y
```

### 方式二：对话式安装

在码道对话面板直接输入：

> 从 https://gitcode.com/huaweicloud/huaweicloud-skills 安装 skills 到 ~/.codeartsdoer/skills/

### 方式三：手动创建

打开设置 → 「技能与规则」→ 项目级 → 技能 → 点「+」新建，填写名称与描述，
系统会在当前目录生成 `.codeartsdoer/skills/<name>/` 结构。

## 四、配置认证（AK/SK）

技能调用华为云 API 需要访问密钥：

1. 控制台 → 我的凭证 → 访问密钥 → 新增访问密钥，下载 `credentials.csv`
2. 按技能文档要求配置到对应位置（通常为环境变量或技能目录下的配置文件）
3. **安全约束**：
   - 使用子用户 AK/SK，只授予本项目所需的最小权限（RDS、DCS、OBS、ECS）
   - 不要使用主账号永久 AK
   - 不要把 `credentials.csv` 提交到 Git（本仓库 `.gitignore` 已覆盖 `*.csv` 与 `.env`）
   - 用完建议在控制台禁用该密钥

## 五、典型操作提示词

以下提示词用于满足赛题的「快速开通 RDS/Redis」与「快速部署」要求，
**执行前请确认目标 VPC、规格与费用**。

### 5.1 开通 RDS

> 在 fzg 项目的 VPC 内创建一个 RDS for MySQL 8.0 实例：
> 规格 1 核 2G，SSD 20GB，单机版（非主备），
> 数据库名 fzg，字符集 utf8mb4。创建完成后告诉我内网地址和端口。

### 5.2 开通 DCS（Redis）

> 在同一 VPC 内创建一个 DCS for Redis 6.0 实例，1GB 单机版，
> 创建后告诉我内网连接地址。

### 5.3 创建 OBS 桶

> 创建一个 OBS 桶，名称 fzg-attachments，区域与我的 ECS 相同，
> 开启版本控制，权限设为私有。

### 5.4 部署应用

> 帮我把 /opt/fzg 目录下的项目部署起来：
> 1. 检查 Docker 是否安装
> 2. 从 SWR 拉取 fzg-app:latest 镜像
> 3. 按 deploy/docker-compose.yml 启动 app 和 nginx 两个服务
> 4. 用 curl 检查 http://127.0.0.1:5000/health 是否返回 ok

### 5.5 辅助开发（体现"使用码道写代码"）

> 解释 backend/app/services/rate_limit.py 的滑动窗口实现，指出并发下的潜在问题。

> 为 backend/app/api/spaces.py 的 search_space_items 补充单元测试，
> 覆盖：正常匹配、空关键词、超过 limit、跨空间命中。

## 六、证据留存清单

赛题把该工具列为必选，但无法自动核验使用情况，**过程留痕即材料**。
建议按下列清单逐项截图或录屏，归档到 `docs/assets/codearts/`：

| 编号 | 内容 | 用途 |
| --- | --- | --- |
| 1 | 码道 IDE 登录后的主界面（含账号信息打码） | 证明使用过该工具 |
| 2 | 让智能体解释本项目某个模块的对话截图 | 开发过程 |
| 3 | 让智能体补单元测试并实际通过的结果 | 开发过程 |
| 4 | 安装 `huaweicloud-skills` 的终端输出或对话记录 | Skills 能力 |
| 5 | 用 Skills 创建 RDS 的对话 + 控制台实例列表 | 云资源开通 |
| 6 | 用 Skills 创建 DCS/Redis 的对话 + 控制台实例列表 | 云资源开通 |
| 7 | 用 Skills 部署的对话 + 服务器 `docker ps` 输出 | 部署上线 |
| 8 | 上述过程的录屏（10–20 秒即可） | 可信度最高的证据 |

> 建议第 5–7 项在**首次操作时录屏**，事后补截图的说服力弱很多。

## 七、常见坑

- **菜单名对不上**：不同版本的设置入口名称略有差异，以实际界面为准，不要照抄教程。
- **技能没生效**：确认技能目录层级正确（必须是 `<skills>/<skill-name>/SKILL.md`），
  装完重启 IDE 或新开会话。
- **云 API 报权限不足**：子用户缺少对应服务的 IAM 策略，逐项补授权而不是换主账号。
- **费用失控**：创建实例前确认规格与计费方式，演示结束及时退订；RDS/DCS 按需计费也要记得删。
- **对话上下文过长**：长会话容易跑偏，新任务建议新开会话并重新交代背景。
