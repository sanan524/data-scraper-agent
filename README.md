# data-scraper-agent

中文热点 → AI 打分 → 存 Notion，GitHub Actions 定时跑，全程免费。

面向**自媒体选题**：只要中文内容、48 小时以内、热度证据硬（评论数 / 榜单排名 / 多平台同时在榜）。

- 抓取：百度热搜、头条热榜、B 站排行榜、IT之家/爱范儿/少数派 RSS —— 全部公开接口，无需 key
- 打分：Gemini Flash（免费层，429/503 自动降级到 lite 模型）
- 存储：Notion 数据库（去重靠 URL）
- 调度：GitHub Actions cron，public 仓库不占额度
- 学习：你在 Notion 里把条目标成 `Saved` / `Skip`，下一轮打分自动偏向你的口味

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # macOS/Linux: cp
# 编辑 .env：GEMINI_API_KEY / NOTION_TOKEN / NOTION_DATABASE_ID

python setup.py                 # 自检：env + Notion 库的 10 个属性
python -m scraper.main          # 跑一轮
python -m scraper.main --dry-run  # 只看会入库什么，不写
```

预期输出：

```text
[百度热搜] 30 items
[头条热榜] 30 items
[B站排行榜] 30 items
  [IT之家] 20/60 条
[时效] 丢弃 29 条超过 48 小时的内容
Unique items in this run: 137
  [AI] 20 items → 4 API calls
Done — 19 new, 0 skipped
```

## 数据源

| 源 | 文件 | 特点 |
|---|---|---|
| 百度热搜 | `scraper/sources/baidu_hot.py` | 国内大众话题，无热度值，用排名代替 |
| 头条热榜 | `scraper/sources/toutiao_hot.py` | 带 `HotValue` 热度值 |
| B站排行榜 | `scraper/sources/bilibili_rank.py` | **唯一带真实评论数**（`comments`） |
| 中文媒体 RSS | `scraper/sources/rss.py` | IT之家 / 爱范儿 / 少数派，带发布时间，可做 48h 过滤 |
| Hacker News | `scraper/sources/hackernews.py` | 英文，默认关闭 |

加源：新建 `scraper/sources/xxx.py`，暴露 `fetch() -> list[dict]`，每条至少
`{"name","url","source","date_found"}`，可选 `hours_ago` / `heat` / `comments` / `rank`；
然后在 `config.yaml` 的 `sources` 下加开关，并在 `scraper/main.py` 的 `collect()` 里接一行。

## Notion 库属性（必须一字不差）

`Name`(title) · `URL`(url) · `Source`(select) · `Date Found`(date) · `Status`(select)
· `AI Score`(number) · `Summary`(rich_text) · `Notes`(rich_text) · `Heat`(number) · `Comments`(number) · `批次`(select)

> `批次` 是每轮抓取的时间戳（如 `11-21 09:55`），按它分组就能看出"这一屏是哪次热榜"。
> `Status` 是反馈学习的入口：标 `Saved` = 正样本，标 `Skip` = 负样本，下一轮打分自动偏向你的口味。

## GitHub Actions

`Settings` → `Secrets and variables` → `Actions` → 三个 secret：
`GEMINI_API_KEY` / `NOTION_TOKEN` / `NOTION_DATABASE_ID`

> 不要用 `GITHUB_TOKEN` / `GH_TOKEN` 作 secret 名（保留名，会被忽略）。

## 常踩的坑

| 现象 | 原因 / 修法 |
|---|---|
| `404 object_not_found` | 数据库没 Connect 给 integration |
| `400 validation_error` | 属性名/类型对不上，照上面 10 个逐字核对 |
| `[AI] Skipped` | `GEMINI_API_KEY` 没进环境变量 |
| `429` 频繁 | 免费层 RPM 很紧：调大 `ai.rate_limit_seconds`、减小 `ai.batch_size` |
| `503` | 模型高峰期，会自动降级到 lite，不用管 |
| AI 字段为空 | 看日志里 `解析失败` 那条，通常是输出被截断，调大 `maxOutputTokens` |
| 重复行 | URL 为空导致去重失效，检查源的 `url` 字段 |

## 目录结构

```text
config.yaml              # 所有开关：抓什么、过滤规则、打分参数
profile/context.md       # 你的背景，拼进 AI prompt
scraper/
  main.py                # 协调器（抓 → 去重 → 时效 → 打分 → 入库）
  filters.py             # 规则预过滤
  sources/               # 一个数据源 = 一个文件
ai/
  client.py              # Gemini REST + 降级链 + 超时重试
  pipeline.py            # 批量分析 + 打分 prompt
  memory.py              # 从 Notion 决策里学偏好
storage/notion_sync.py   # 去重、写入、回填、反馈读取
data/feedback.json       # 偏好历史（Actions 每轮自动 commit）
setup.py                 # 自检
enrich_existing.py       # 给历史行补 AI 分数
feedback_sync.py         # 单独刷新偏好
```
