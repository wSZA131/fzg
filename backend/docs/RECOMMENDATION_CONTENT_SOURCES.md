# 探索推荐内容来源

## 原则

首页“探索”是额外的外部资源补充推荐，只展示通过服务端 API 获取的真实资源。来源包括开放教育资源，以及在配置 Key 后启用的商业图书搜索；商业图书会明确标记来源。

不进入探索推荐的内容：

- 用户空间里的笔记、文件、链接
- AI 生成的讲解卡片
- 题库练习、复习任务

用户画像、知识图谱和复习状态只用于决定查询哪些外部主题，不作为内容卡片返回。

## 查询主题怎么来

只从以下已有信号中选择主题：

- 掌握度低于 0.6 的薄弱知识点
- 已到复习时间的知识点
- 用户画像中的兴趣主题

没有这些信号时，不查询外部 API，也不展示人工“精选”内容。

## 开放资源

### Wikipedia

- 接口：MediaWiki Action API
- 默认域名：`https://zh.wikipedia.org/w/api.php`
- 使用 `generator=search`、`prop=extracts|pageimages|info`
- 只读取标题、摘要、缩略图和条目链接
- 不抓取页面 HTML

### Wikibooks 开放教材

- 接口：MediaWiki Action API
- 域名：`https://zh.wikibooks.org/w/api.php`
- 资源类型标记为 `open_textbook`
- 可通过 `OPEN_TEXTBOOKS_ENABLED=0` 关闭

### OpenStax

- 接口：OpenStax CMS / Wagtail API
- 书籍索引：`https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=title,description,cover_url&limit=200`
- 只读取书名、描述、封面和官方详情页链接
- 本地缓存 24 小时，按中文学科关键词映射到英文书名/描述
- 仅链接到 OpenStax 官方页面，不复制教材正文
- 可通过 `OPENSTAX_ENABLED=0` 关闭

OpenStax 教材通常采用 CC BY-NC-SA 许可，适合非商业学习推荐和引用；保留来源名称和官方链接。

### Oak National Academy

- 接口：Oak Curriculum API v1
- 搜索：`GET https://open-api.thenational.academy/api/v1/search/lessons?q=...`
- 鉴权：`Authorization: Bearer <OAK_API_KEY>`
- 只读取课程标题、官方课程链接、匹配度、所属单元/学科
- 不下载视频、课件或完整课程正文
- 无 Key 时自动跳过，不影响其他来源
- 使用时应署名 “Oak National Academy”

```bash
OAK_API_KEY=your_oak_api_key
```

### SerpApi 学习类引擎

- 鉴权：`SERPAPI_API_KEY`
- 目前接入 4 个适合学习资源的引擎：
  - `google_scholar`：论文，资源类型 `open_paper`
  - `google_books`：图书，资源类型 `external_book`
  - `google_videos`：视频，资源类型 `open_video`
  - `google_play_books`：商业图书，资源类型 `external_book`
- 地图、购物、航班、招聘、新闻等与学习推荐无关的引擎不接入
- 只读取标题、作者/摘要、封面、简介和官方链接
- 不复制或展示受版权保护的正文
- 无 Key 时自动跳过

```bash
SERPAPI_API_KEY=your_serpapi_key
SERPAPI_ENGINES=google_scholar,google_books,google_videos,google_play_books
SERPAPI_MAX_QUERIES=2
```

`SERPAPI_MAX_QUERIES` 控制每次推荐最多用几个主题调用 SerpApi，默认 2，避免一次消耗过多额度。所有引擎结果缓存 6 小时。

SerpApi 是第三方付费搜索服务，使用前需要确认其套餐、配额和各引擎的展示条款。Google Books、Google Play Books 属于商业图书，卡片会明确标记为 `图书`。

### YouTube

- 接口：YouTube Data API v3 `search.list`
- 需要配置官方 API Key：

```bash
YOUTUBE_API_KEY=your_google_api_key
```

- 只读取视频标题、描述、频道、缩略图和视频链接
- 未配置 Key 时自动跳过 YouTube
- 不通过爬虫解析 YouTube 页面

## 配置

```bash
WIKIPEDIA_LANGUAGES=zh
OPEN_TEXTBOOKS_ENABLED=1
OPENSTAX_ENABLED=1
OPENSTAX_CATALOG_TTL_SECONDS=86400
OAK_API_KEY=
SERPAPI_API_KEY=
SERPAPI_ENGINES=google_scholar,google_books,google_videos,google_play_books
SERPAPI_MAX_QUERIES=2
YOUTUBE_API_KEY=
OPEN_RESOURCE_TIMEOUT_SECONDS=1.8
OPEN_RESOURCE_CACHE_TTL_SECONDS=21600
OPEN_RESOURCE_MAX_QUERIES=4
```

发送给开放 API 的只有主题词，不发送 `user_id`、空间正文、题目内容或对话内容。查询结果会按主题缓存 6 小时，避免重复请求。

## 公开教育数据集

以下数据集适合离线实验，不得作为线上推荐卡片：

- EdNet
- ASSISTments
- Junyi Academy

可离线用于：

- 知识追踪模型验证
- 推荐排序模型评估
- 冷启动策略对比

线上接口不会读取这些数据集，也不会把数据集中的题目或交互记录直接返回给用户。
