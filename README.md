# 伪人

`伪人` 是一个本地运行的人物记忆整理与检索系统。

系统围绕三件事构建：

- 原始资料可导入
- 结构化结果可校正
- 所有结论可回溯到证据

项目适合整理历史聊天记录、零散文本、PDF、图片时间信息和人工补充描述，并在本地完成检索、问答、校正、去重与导出。

可选接入本地大语言模型（Ollama），对固定问答和聊天提供更自然的口语化回答，同时保留证据回溯能力。关闭 LLM 时回退到纯规则模板回答，不产生任何外部请求。

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

搜索基于 `SQLite FTS5 + RapidFuzz`，未引入任何外部检索系统。

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

### 4. 问答与聊天

固定问答 `/qa` 和自由聊天 `/chat` 共享同一套检索引擎：

- 规则意图识别
- FTS 全文检索
- RapidFuzz 相似句匹配
- 模板化回答

**可选 LLM 增强**：在 `/settings` 开启"启用 LLM 增强回答"后，有证据支撑的问题会调用本地 Ollama 生成更自然的口语化回答，同时保留证据来源展示。关闭时回退到模板回答，不产生任何外部请求。

支持的问题类型包括：

- 她喜欢吃什么？
- 她不喜欢什么？
- 她平时说话是什么感觉？
- 她经常怎么称呼我？
- 她说过哪些最像她风格的话？
- 我们在某段时间发生过什么？
- 她通常会因为什么不高兴？

聊天页 `/chat` 提供多会话支持的连续对话体验，自动关联同一个人物的资料。

### 5. 证据链与人工校正

- 结构化数据的证据链视图
- 固定问答和聊天结果的证据展示
- 手工校正台 `/review`
- 低可信/已确认状态标记
- 修改历史记录 `change_logs`

### 6. 去重、导出、隐私控制

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
- httpx
- Ollama（可选，仅 LLM 增强模式需要）

## 页面与路由

- `/` 首页
- `/import` 导入页
- `/profile` 人物资料页
- `/timeline` 时间线页
- `/search` 搜索页
- `/chat` 聊天页
- `/qa` 固定问答页
- `/review` 手工校正台
- `/dedupe` 重复识别与合并页
- `/export` 导出页
- `/settings` 隐私、演示模式与 LLM 设置页
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
│   ├── import_service.py
│   ├── parsers.py
│   ├── extraction.py
│   ├── qa_service.py
│   ├── chat_service.py
│   ├── llm_service.py        # Ollama 调用封装
│   ├── search_service.py
│   ├── search_index_service.py
│   ├── evidence_service.py
│   ├── review_service.py
│   ├── dedupe_service.py
│   ├── export_service.py
│   └── settings_service.py
├── utils/
├── templates/
└── static/
scripts/
sample_data/
start.sh           # Linux/macOS 一键启动
start.bat          # Windows 一键启动
requirements.txt
README.md
```

## 快速开始

### 一键启动

Linux / macOS：

```bash
chmod +x start.sh
./start.sh
```

Windows：

双击 `start.bat`，或在终端中运行：

```cmd
start.bat
```

脚本会自动完成：创建虚拟环境 → 安装依赖 → 初始化数据库 → 启动服务。

启动后访问 http://127.0.0.1:8000/

### 手动启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
uvicorn weiren.main:app --reload --host 127.0.0.1 --port 8000
```

### 样例数据

```bash
python scripts/generate_sample_assets.py
python scripts/load_sample_data.py
```

### 可选：重编译 Tailwind CSS

仓库已提交编译产物，直接运行不依赖 Node。只有在修改样式源码后才需要：

```bash
npm install
npm run build:css
```

## LLM 增强配置（可选）

1. 确保局域网内有可用的 Ollama 实例（默认地址 `http://172.16.18.176:11434`）
2. 确保已拉取模型（默认 `gemma4:e2b`）
3. 启动后访问 `/settings`，勾选"启用 LLM 增强回答"
4. 在 `/qa` 或 `/chat` 页面提问即可体验

如需修改 Ollama 地址或模型名，编辑 `weiren/services/llm_service.py` 中的 `DEFAULT_BASE_URL` 和 `DEFAULT_MODEL`。

LLM 严格遵守"仅依据提供的资料回答"原则，不会调用自身知识。回答末尾仍附带证据来源。

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

辅助表：

- `evidence_links`
- `change_logs`
- `export_records`
- `dedupe_candidates`
- `qa_records`
- `chat_sessions`
- `chat_messages`
- `app_settings`
- `search_presets`
- `search_history`

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

## 隐私与演示模式

系统支持本地脱敏与演示展示控制：

- 隐藏真实姓名
- 隐藏电话号码
- 隐藏地点
- 隐藏社交账号
- 演示模式下优先显示摘要或脱敏内容

设置入口：`/settings`

## 测试

```bash
python scripts/run_smoke_tests.py
```

该脚本会：初始化数据库 → 生成样例数据 → 批量导入 → 检查所有页面是否可访问。

## 设计原则

- 本地优先
- 来源优先
- 证据优先
- 规则优先
- 可人工校正
- 可验证，不虚构
- LLM 可选、可关闭，关闭后不产生任何外部请求

## 适用边界

`伪人` 不是聊天机器人，也不是关系模拟器。它不会"理解你们的关系"，也不会替你推断不存在的内容。

它做的事是：

- 把已有资料整理成结构化档案
- 让搜索更快
- 让问答更可追溯
- 让人工修正更方便
- 让导出与展示更稳妥
