# data-scraper-agent

抓取 → AI 打分 → 存 Notion，GitHub Actions 定时跑，全程免费。

- 抓取：`requests` + Algolia 公开 API（Hacker News），无需 key
- 打分：Gemini Flash（免费额度，429 自动降级到更省的模型）
- 存储：Notion 数据库（去重靠 URL）
- 调度：GitHub Actions cron，public 仓库不占额度
- 学习：你在 Notion 里把条目标成 `Saved` / `Skip`，下一轮打分自动偏向你的口味

## 快速开始

### 1. 本地跑通

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # macOS/Linux: cp
# 编辑 .env，填 GEMINI_API_KEY / NOTION_TOKEN / NOTION_DATABASE_ID

python setup.py                 # 自检：env + Notion 库的 8 个属性
python -m scraper.main          # 跑一轮
```

预期输出：

```text
[Hacker News] 42 items
Unique items in this run: 38
Already in Notion: 0 | New: 38
  [AI] 38 items → 8 API calls
Done — 20 new, 18 skipped
```

### 2. 上 GitHub Actions

仓库 → `Settings` → `Secrets and variables` → `Actions` → 三个 secret：

| Secret | 值 |
|---|---|
| `GEMINI_API_KEY` | `AIza...` |
| `NOTION_TOKEN` | `ntn_...` |
| `NOTION_DATABASE_ID` | 32 位 ID |

然后 `Actions` → `Data Scraper Agent` → `Run workflow`。

> 不要用 `GITHUB_TOKEN` / `GH_TOKEN` 作 secret 名，那是保留名。

## 目录结构

```text
config.yaml              # 所有开关：抓什么、怎么过滤、怎么打分
profile/context.md       # 你的背景，拼进 AI prompt
scraper/
  main.py                # 协调器
  filters.py             # 规则预过滤（AI 之前跑，省额度）
  sources/hackernews.py  # 一个数据源 = 一个文件
ai/
  client.py              # Gemini REST + 模型降级链
  pipeline.py            # 批量分析
  memory.py              # 从 Notion 决策里学偏好
storage/notion_sync.py   # 去重、写入、回填、反馈读取
data/feedback.json       # 偏好历史（Actions 每轮自动 commit）
setup.py                 # 自检
enrich_existing.py       # 给历史行补 AI 分数
feedback_sync.py         # 单独刷新偏好
```

## 加一个数据源

新建 `scraper/sources/my_source.py`，暴露 `fetch() -> list[dict]`，每条至少有：

```python
{"name": "...", "url": "...", "source": "MySource", "date_found": "YYYY-MM-DD"}
```

然后在 `config.yaml` 的 `sources` 下加开关，并在 `scraper/main.py` 的 `collect()` 里接一行。

## 常踩的坑

| 现象 | 原因 |
|---|---|
| `404 object_not_found` | 数据库没 Connect 给 integration |
| `400 validation_error` | 属性名/类型对不上（必须是 `Name` `URL` `Source` `Date Found` `Status` `AI Score` `Summary` `Notes`） |
| `[AI] Skipped` | `GEMINI_API_KEY` 没进环境变量 |
| `429` | 调大 `ai.rate_limit_seconds`、`ai.batch_size`，或缩小 `filters.max_items` |
| 重复行 | URL 为空导致去重失效，检查源是否返回了 `url` |
