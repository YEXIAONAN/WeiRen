# 伪人

`伪人` 是一个本地运行的人物记忆整理与检索系统。

它不接入任何大语言模型，不依赖 OpenAI、Claude、Ollama、Dify、LangChain、向量数据库，也不做在线推理。系统围绕三件事构建：

- 原始资料可导入
- 结构化结果可校正
- 所有结论可回溯到证据

项目适合整理历史聊天记录、零散文本、PDF、图片时间信息和人工补充描述，并在本地完成检索、问答、校正、去重与导出。

## 当前版本能力

### 1. 导入与解析

支持导入：

- `txt`
- `md`
- `json`
- `csv`
- `pdf`
- `jpg`
- `png`
- 手工输入文本

解析能力包括：

- 文本按段落切分
- 聊天记录基础识别
- PDF 纯文本提取
- 图片 EXIF 时间或文件时间提取
- 关键词、人物、日期的规则抽取

### 2. 结构化整理

系统会把导入内容整理到以下维度：

- 人物特征 `traits`
- 喜好厌恶 `preferences`
- 典型原话 `quotes`
- 共同记忆 `memories`
- 时间线事件 `timeline_events`
- 原始消息 `messages`
- 来源文件 `sources`

### 3. 搜索系统

搜索仍然完全基于 `SQLite FTS5 + RapidFuzz`，未引入任何外部检索系统。

支持：

- 全文关键词搜索
- 命中高亮
- 相似句检索
- 来源过滤
- 时间范围过滤
- 高级搜索语法
- 搜索历史记录
- 搜索条件保存
- 与当前结果相关的其他片段推荐

已支持的高级语法：

- `type:quote`
- `type:memory`
- `source:pdf`
- `source:json`
- `date:2024-10`
- `date:2024-10-07`
- `tag:food`
- `tag:emotion`

可组合使用，例如：

```text
type:quote source:json date:2024-08 咖啡
```

### 4. 固定问答

问答模块使用：

- 规则意图识别
- FTS 全文检索
- RapidFuzz 相似句匹配
- 模板化回答

回答必须来自数据库内容，不允许虚构，并附带证据来源。

支持的问题类型包括：

- 她喜欢吃什么？
- 她不喜欢什么？
- 她平时说话是什么感觉？
- 她经常怎么称呼我？
- 她说过哪些最像她风格的话？
- 我们在某段时间发生过什么？
- 她通常会因为什么不高兴？

### 5. 证据链与人工校正

v1.5 已补充：

- 结构化数据的证据链视图
- 固定问答结果的证据展示
- 手工校正台 `/review`
- 低可信/已确认状态标记
- 修改历史记录 `change_logs`

### 6. 去重、导出、隐私控制

已实现：

- 重复内容识别与待合并列表 `/dedupe`
- 手工保留 / 手工合并相似记录
- 资料卡、时间线、问答记录 Markdown 导出
- 完整档案 ZIP 导出
- 演示模式与脱敏规则
- 电话、地点、社交账号、姓名脱敏

## 技术栈

- Python 3.11+
- FastAPI
- SQLModel
- SQLite
- SQLite FTS5
- Jinja2
- Tailwind CSS
- 原生 JavaScript
- PyMuPDF
- Pillow
- RapidFuzz
- jieba

## 明确不使用

- 大语言模型
- 第三方 AI SDK
- 向量数据库
- Elasticsearch
- Redis
- PostgreSQL
- 微服务
- 在线推理能力

## 页面与路由

当前主要页面：

- `/` 首页
- `/import` 导入页
- `/profile` 人物资料页
- `/timeline` 时间线页
- `/search` 搜索页
- `/qa` 固定问答页
- `/review` 手工校正台
- `/dedupe` 重复识别与合并页
- `/export` 导出页
- `/settings` 隐私与演示模式设置页
- `/evidence/{entity_type}/{entity_id}` 证据详情页

## 项目结构

```text
weiren/
├── main.py
├── routes.py
├── config.py
├── db.py
├── models.py
├── services/
├── utils/
├── templates/
└── static/
scripts/
sample_data/
requirements.txt
README.md
```

## 数据表概览

核心表：

- `sources`
- `messages`
- `memories`
- `preferences`
- `traits`
- `quotes`
- `timeline_events`
- `search_documents`
- `search_documents_fts`

v1.5 新增：

- `evidence_links`
- `change_logs`
- `export_records`
- `dedupe_candidates`
- `qa_records`
- `app_settings`
- `search_presets`
- `search_history`

## 安装

### 1. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 可选：重编译 Tailwind CSS

仓库已提交编译产物 `weiren/static/css/tailwind.css`。
直接运行应用不依赖 Node。只有在修改样式源码后才需要重新构建：

```bash
npm install
npm run build:css
```

## 初始化数据库

```bash
python scripts/init_db.py
```

默认数据库位置：

```text
data/weiren.db
```

## 生成样例数据

```bash
python scripts/generate_sample_assets.py
```

会在 `sample_data/` 下生成示例文件，包括：

- `chat_fragments.txt`
- `memory_notes.md`
- `chat_export.json`
- `chat_export.csv`
- `duplicate_quotes.json`
- `private_notes.txt`
- `weekly_report.pdf`
- `night_walk.jpg`
- `station_window.png`

## 导入样例数据

```bash
python scripts/load_sample_data.py
```

也可以启动服务后直接在 `/import` 页面上传。

## 启动

```bash
uvicorn weiren.main:app --reload
```

启动后访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/import`
- `http://127.0.0.1:8000/profile`
- `http://127.0.0.1:8000/timeline`
- `http://127.0.0.1:8000/search`
- `http://127.0.0.1:8000/qa`
- `http://127.0.0.1:8000/review`
- `http://127.0.0.1:8000/dedupe`
- `http://127.0.0.1:8000/export`
- `http://127.0.0.1:8000/settings`

## 搜索示例

### 基础搜索

```text
冷战 咖啡
```

### 限定为原话

```text
type:quote 重点
```

### 限定来源类型

```text
source:pdf nostalgic
```

### 限定月份

```text
date:2024-10 车站
```

### 标签筛选

```text
tag:food type:quote
```

## 固定问答示例

- `她喜欢吃什么？`
- `她不喜欢什么？`
- `她平时说话是什么感觉？`
- `她经常怎么称呼我？`
- `她说过哪些最像她风格的话？`
- `我们在某段时间发生过什么？`
- `她通常会因为什么不高兴？`

## 隐私与演示模式

系统支持本地脱敏与演示展示控制：

- 隐藏真实姓名
- 隐藏电话号码
- 隐藏地点
- 隐藏社交账号
- 演示模式下优先显示摘要或脱敏内容

相关设置页面：

- `/settings`

## 测试与验证

项目提供基础烟雾测试脚本：

```bash
python scripts/run_smoke_tests.py
```

该脚本会：

- 初始化数据库
- 生成样例数据
- 批量导入样例文件
- 检查首页、搜索、校正、去重、导出、证据、问答等页面是否可访问

## 设计原则

- 本地优先
- 来源优先
- 证据优先
- 规则优先
- 可人工校正
- 可验证，不虚构

## 适用边界

`伪人` 不是聊天机器人，也不是关系模拟器。它不会“理解你们的关系”，也不会替你推断不存在的内容。

它做的事是：

- 把已有资料整理成结构化档案
- 让搜索更快
- 让问答更可追溯
- 让人工修正更方便
- 让导出与展示更稳妥
