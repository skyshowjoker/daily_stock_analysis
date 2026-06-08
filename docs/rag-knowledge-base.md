# 投资 RAG 知识库

本功能用于把投资相关知识和个人偏好沉淀到本地知识库中，支持文章、新闻、书籍摘录、研究笔记和偏好约束。知识库默认使用本地 SQLite 表存储原始文档元数据与 chunk，并使用 SQLite FTS5/BM25 加中文友好的词法兜底检索。

> 当前版本不自动抓取 URL。Web 页面中的“来源 URL / 书籍定位”只用于溯源，正文需要用户明确粘贴提交，避免 SSRF、登录态泄露、版权和不可控网页清洗问题。

## 能力范围

- Web 入口：`/knowledge`
  - 投喂标题、来源类型、来源 URL、作者、发布日期、标签和正文。
  - 投喂后自动清洗、去重、分块和索引。
  - 同页提供检索验证入口，用于检查材料是否可被召回。
- API：
  - `POST /api/v1/rag/documents`：投喂文档。
  - `GET /api/v1/rag/documents`：分页查看文档。
  - `GET /api/v1/rag/documents/{document_id}`：查看文档及 chunk。
  - `DELETE /api/v1/rag/documents/{document_id}`：删除文档及索引。
  - `POST /api/v1/rag/search`：检索相关 chunk。
  - `GET /api/v1/rag/stats`：查看文档数、chunk 数和分块参数。
- Agent 工具：
  - `search_investment_knowledge`：按问题、关键词和标签检索投资知识库。
  - `get_investment_knowledge_stats`：查看知识库规模和检索模式。

## RAG 设计原则

1. **先保证可追溯**
   - 每条结果返回 `document_id`、`chunk_id`、标题、来源类型、来源 URI、标签、chunk 序号和检索分数。
   - Agent 使用召回结果时可以引用出处，而不是把偏好直接混进系统 Prompt。

2. **先做稳健的本地检索**
   - 默认不依赖外部 embedding 服务，避免私有偏好材料离开本地环境。
   - SQLite FTS5 负责 BM25 关键词召回，中文词法兜底使用单字与二元组，降低中文未分词导致的漏召回。
   - `rag_chunks` 预留 embedding 字段，后续可接入向量模型或外部向量库而不改变文档/chunk 契约。

3. **控制上下文污染**
   - 投喂不会自动进入每次分析 Prompt。
   - Agent 需要时通过工具按问题检索，降低无关材料挤占上下文、过期偏好影响结论的风险。

4. **去重和可删除**
   - 文档正文会计算 SHA-256 哈希；默认遇到相同正文时返回已有文档，不重复入库。
   - 勾选 `replace_existing` 可替换同正文旧文档。
   - 删除文档会同时清理 chunk 和 FTS 索引。

## 输入建议

- 文章 / 新闻：粘贴正文，并在 `source_uri` 保存原文链接。
- 书籍：建议按章节或主题摘录，不要一次投喂整本书；标题中包含书名和章节。
- 个人偏好：使用 `preference` 来源类型，并加 `preference`、`risk`、`valuation` 等标签。
- 高价值材料：给出明确标签，例如 `周期股`、`现金流`、`仓位管理`、`止损纪律`，有助于后续过滤召回。

示例偏好：

```text
我的投资偏好：
1. 优先选择现金流稳定、负债率较低、管理层资本配置克制的公司。
2. 对高杠杆周期股保持谨慎，除非有明确供需拐点和安全边际。
3. 单笔交易亏损达到 8% 时必须重新评估，不因短期情绪加仓。
```

## 配置项

配置项均为可选，默认即可运行。新增或调整后需要重启后端服务。

```bash
# 单个 chunk 目标字符数，默认 1200，允许范围 300-4000。
RAG_CHUNK_SIZE=1200

# 相邻 chunk 重叠字符数，默认 180，最大不超过 chunk_size 的一半。
RAG_CHUNK_OVERLAP=180

# 默认召回 chunk 数，默认 8，允许范围 1-30。
RAG_DEFAULT_TOP_K=8
```

## 存储位置

RAG 使用项目现有 `DatabaseManager` 和数据库 URL。默认部署通常是 SQLite 数据库；新表包括：

- `rag_documents`：文档级元数据、正文哈希、来源类型、标签、chunk 数。
- `rag_chunks`：chunk 内容、hash、字符数、token 估算和未来 embedding 字段。
- `rag_chunks_fts`：SQLite FTS5 虚拟表，用于本地全文检索。

如果未来切换到非 SQLite 数据库，需要补充对应全文检索或向量检索实现；当前本地 FTS5 路径以 SQLite 为主。

## 排障

- 投喂失败提示 `content exceeds max length`：单篇正文超过 1,000,000 字符，建议按章节拆分。
- 检索没有结果：先确认正文里包含相近关键词，或给材料补充更明确标签；中文长句可尝试拆成短关键词。
- 删除后仍看到旧结果：刷新 `/knowledge` 页面；若数据库被外部工具修改，重启后端可重建服务实例。

## 回滚

- 功能级回滚：删除本次新增/修改的 RAG 相关代码并重启服务。
- 数据级清理：在确认不需要保留知识库后，备份数据库，再清理 `rag_documents`、`rag_chunks` 和 `rag_chunks_fts`。
- 配置级回滚：移除 `.env` 中 `RAG_*` 配置并重启，系统会回到默认分块和召回参数。
