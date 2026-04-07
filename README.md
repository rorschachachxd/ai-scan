# AI Scan - Real-time AI News Aggregator

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## English

### Overview

**AI Scan** is a real-time AI news aggregation tool that fetches, deduplicates, scores, and summarizes the latest AI news from multiple sources. It's faster than RSS and provides intelligent filtering to surface the most relevant stories.

### Features

- **Multi-source aggregation**: Hacker News, Reddit, GitHub, ArXiv, Hugging Face, AI company blogs
- **Smart deduplication**: Cross-source duplicate detection using similarity matching
- **Intelligent scoring**: Ranks stories by relevance, freshness, and engagement
- **AI-powered summaries**: Automatic 1-2 sentence summaries for each story
- **Flexible output**: Markdown, JSON, or Feishu-ready bilingual format
- **Persistent tracking**: SQLite database prevents showing duplicate stories

### Quick Start

#### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ai-scan.git
cd ai-scan

# Install dependencies
pip3 install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env and add your DASHSCOPE_API_KEY
```

#### Basic Usage

```bash
# Default: all sources, last 12 hours
python3 ai_scan.py

# Quick scan: HN + Reddit only, last 2 hours
python3 ai_scan.py --quick

# Deep scan: all sources, last 48 hours
python3 ai_scan.py --deep

# Skip AI summarization (faster)
python3 ai_scan.py --no-summarize

# JSON output
python3 ai_scan.py --json

# Feishu bilingual format
python3 ai_scan.py --feishu
```

### Configuration

#### API Keys

The tool requires a **DashScope API key** for AI summarization:

1. Visit [DashScope Console](https://dashscope.console.aliyun.com/)
2. Create an account and generate an API key
3. Add to `.env` file:
   ```
   DASHSCOPE_API_KEY=your_key_here
   ```

Optional: X/Twitter API bearer token for Twitter news (most sources work without it).

#### Command-Line Options

| Option | Description |
|--------|-------------|
| `--quick` | Fast scan: HN + Reddit only, last 2h |
| `--deep` | All sources, last 48h |
| `--sources LIST` | Comma-separated: `hn,reddit,github,arxiv,hf,blogs,x` |
| `--no-summarize` | Skip AI summarization (raw titles only) |
| `--json` | JSON output for piping |
| `--feishu` | Feishu card-ready bilingual output |
| `--hours N` | Custom lookback window in hours (default: 12) |

### Data Sources

| Source | Update Frequency | API Cost |
|--------|-----------------|----------|
| Hacker News | Minutes | Free |
| Reddit (r/LocalLLaMA, r/MachineLearning, etc.) | Minutes | Free |
| GitHub Trending + Search | Hours | Free |
| ArXiv (cs.AI/CL/LG/CV) | Hours | Free |
| Hugging Face Blog | Hours | Free |
| AI Company Blogs (Google, DeepMind, OpenAI) | Hours-Days | Free |
| X/Twitter | Minutes | Requires API Key |

### Output Format

The tool generates a Markdown report with:

- **Top Stories**: High-scoring items (score ≥ 40) with full summaries
- **ArXiv Papers**: Latest research papers
- **GitHub Trending**: New AI repositories
- **Blog Posts**: Company announcements and technical posts

Each item includes:
- Title and URL
- Source and metadata (points, comments, stars)
- Age (e.g., "2h ago")
- AI-generated summary

### Architecture

```
User invokes
    ↓
Multi-source fetch (parallel)
    ↓
In-memory deduplication (similarity key)
    ↓
Relevance scoring (engagement + freshness + keywords)
    ↓
Database deduplication (48h window)
    ↓
AI summarization (batch processing)
    ↓
Markdown/JSON output
```

### Advanced Usage

#### Custom Source Selection

```bash
# Only Hacker News and Reddit, last 6 hours
python3 ai_scan.py --sources hn,reddit --hours 6

# GitHub and ArXiv only
python3 ai_scan.py --sources github,arxiv
```

#### Integration with Other Tools

```bash
# Pipe to file
python3 ai_scan.py > ai_news.md

# JSON for processing
python3 ai_scan.py --json | jq '.items[] | select(.score > 60)'

# Cron job (every 2 hours)
0 */2 * * * cd /path/to/ai-scan && python3 ai_scan.py --quick >> daily_news.md
```

### Scoring Algorithm

Each story receives a score (0-100) based on:

- **Source signal (40%)**: Engagement metrics (upvotes, stars, comments)
- **Freshness (30%)**: Exponential decay with 12-hour half-life
- **Keyword relevance (20%)**: Matches against AI-related terms
- **Source weight (10%)**: Inherent reliability of the source

### Database

The tool maintains a SQLite database (`ai_scan.db`) to track seen items:

- **URL-based deduplication**: Prevents exact duplicates
- **Similarity-based deduplication**: Catches cross-posts and rewrites (48h window)
- **Auto-pruning**: Removes entries older than 30 days

### Troubleshooting

**No API key error:**
```bash
# Make sure .env file exists and contains your key
cat .env
export DASHSCOPE_API_KEY=your_key_here
python3 ai_scan.py
```

**Rate limiting:**
- The tool includes automatic retry logic for 429 errors
- Add delays between requests if needed

**Empty results:**
- Try increasing the time window: `--hours 24`
- Check if sources are accessible from your network

### Contributing

Contributions welcome! Areas for improvement:

- Additional news sources
- Better scoring algorithms
- Multi-language support
- Performance optimizations

### License

MIT License - see [LICENSE](LICENSE) file for details.

---

<a name="中文"></a>
## 中文

### 概述

**AI Scan** 是一个实时 AI 新闻聚合工具，从多个来源获取、去重、评分并总结最新的 AI 新闻。比 RSS 更快，提供智能过滤以突出最相关的故事。

### 功能特性

- **多源聚合**：Hacker News、Reddit、GitHub、ArXiv、Hugging Face、AI 公司博客
- **智能去重**：使用相似度匹配的跨源重复检测
- **智能评分**：根据相关性、新鲜度和参与度对故事进行排名
- **AI 驱动摘要**：为每个故事自动生成 1-2 句摘要
- **灵活输出**：Markdown、JSON 或飞书就绪的双语格式
- **持久化跟踪**：SQLite 数据库防止显示重复故事

### 快速开始

#### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/ai-scan.git
cd ai-scan

# 安装依赖
pip3 install -r requirements.txt

# 配置 API 密钥
cp .env.example .env
# 编辑 .env 并添加你的 DASHSCOPE_API_KEY
```

#### 基本用法

```bash
# 默认：所有来源，最近 12 小时
python3 ai_scan.py

# 快速扫描：仅 HN + Reddit，最近 2 小时
python3 ai_scan.py --quick

# 深度扫描：所有来源，最近 48 小时
python3 ai_scan.py --deep

# 跳过 AI 摘要（更快）
python3 ai_scan.py --no-summarize

# JSON 输出
python3 ai_scan.py --json

# 飞书双语格式
python3 ai_scan.py --feishu
```

### 配置

#### API 密钥

该工具需要 **DashScope API 密钥** 用于 AI 摘要：

1. 访问 [DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 创建账户并生成 API 密钥
3. 添加到 `.env` 文件：
   ```
   DASHSCOPE_API_KEY=你的密钥
   ```

可选：X/Twitter API bearer token 用于 Twitter 新闻（大多数来源无需此密钥即可工作）。

#### 命令行选项

| 选项 | 描述 |
|------|------|
| `--quick` | 快速扫描：仅 HN + Reddit，最近 2 小时 |
| `--deep` | 所有来源，最近 48 小时 |
| `--sources LIST` | 逗号分隔：`hn,reddit,github,arxiv,hf,blogs,x` |
| `--no-summarize` | 跳过 AI 摘要（仅原始标题） |
| `--json` | JSON 输出用于管道处理 |
| `--feishu` | 飞书卡片就绪的双语输出 |
| `--hours N` | 自定义回溯时间窗口（小时，默认：12） |

### 数据源

| 来源 | 更新频率 | API 成本 |
|------|---------|---------|
| Hacker News | 分钟级 | 免费 |
| Reddit (r/LocalLLaMA, r/MachineLearning 等) | 分钟级 | 免费 |
| GitHub Trending + 搜索 | 小时级 | 免费 |
| ArXiv (cs.AI/CL/LG/CV) | 小时级 | 免费 |
| Hugging Face 博客 | 小时级 | 免费 |
| AI 公司博客 (Google, DeepMind, OpenAI) | 小时-天级 | 免费 |
| X/Twitter | 分钟级 | 需要 API 密钥 |

### 输出格式

该工具生成包含以下内容的 Markdown 报告：

- **热点头条**：高分项目（分数 ≥ 40）及完整摘要
- **ArXiv 论文**：最新研究论文
- **GitHub 趋势**：新的 AI 仓库
- **博客文章**：公司公告和技术文章

每个项目包括：
- 标题和 URL
- 来源和元数据（点赞数、评论数、星标数）
- 时间（例如 "2h ago"）
- AI 生成的摘要

### 架构

```
用户调用
    ↓
多源获取（并行）
    ↓
内存去重（相似度键）
    ↓
相关性评分（参与度 + 新鲜度 + 关键词）
    ↓
数据库去重（48 小时窗口）
    ↓
AI 摘要（批处理）
    ↓
Markdown/JSON 输出
```

### 高级用法

#### 自定义来源选择

```bash
# 仅 Hacker News 和 Reddit，最近 6 小时
python3 ai_scan.py --sources hn,reddit --hours 6

# 仅 GitHub 和 ArXiv
python3 ai_scan.py --sources github,arxiv
```

#### 与其他工具集成

```bash
# 输出到文件
python3 ai_scan.py > ai_news.md

# JSON 用于处理
python3 ai_scan.py --json | jq '.items[] | select(.score > 60)'

# Cron 任务（每 2 小时）
0 */2 * * * cd /path/to/ai-scan && python3 ai_scan.py --quick >> daily_news.md
```

### 评分算法

每个故事根据以下因素获得分数（0-100）：

- **来源信号（40%）**：参与度指标（点赞、星标、评论）
- **新鲜度（30%）**：12 小时半衰期的指数衰减
- **关键词相关性（20%）**：与 AI 相关术语的匹配
- **来源权重（10%）**：来源的固有可靠性

### 数据库

该工具维护一个 SQLite 数据库（`ai_scan.db`）来跟踪已见项目：

- **基于 URL 的去重**：防止完全重复
- **基于相似度的去重**：捕获跨平台转发和改写（48 小时窗口）
- **自动清理**：删除超过 30 天的条目

### 故障排除

**无 API 密钥错误：**
```bash
# 确保 .env 文件存在并包含你的密钥
cat .env
export DASHSCOPE_API_KEY=你的密钥
python3 ai_scan.py
```

**速率限制：**
- 该工具包含 429 错误的自动重试逻辑
- 如需要可在请求之间添加延迟

**空结果：**
- 尝试增加时间窗口：`--hours 24`
- 检查你的网络是否可以访问这些来源

### 贡献

欢迎贡献！改进方向：

- 额外的新闻源
- 更好的评分算法
- 多语言支持
- 性能优化

### 许可证

MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

---

## Technical Details

### Dependencies

- Python 3.7+
- `requests` library for HTTP requests
- SQLite3 (included in Python standard library)

### Performance

- Typical scan time: 10-30 seconds (depending on sources)
- Database size: ~1-5 MB (auto-pruned)
- Memory usage: <50 MB

### Privacy

- No telemetry or tracking
- All data stored locally in SQLite database
- API keys stored in local `.env` file only

---

**Star this repo if you find it useful!** ⭐
