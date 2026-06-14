# 投资 RAG 知识库

本功能用于把投资相关文章、新闻、研究报告、书籍和个人偏好沉淀到本地知识库。主要输入方式是上传文档，用户不需要填写标题、来源、分类、标签或正文；系统会自动解析文本、生成摘要、分类、打标签、去重、分块和索引。

知识库默认使用本地 SQLite 表存储文档元数据与 chunk，并使用 SQLite FTS5/BM25 加中文友好的词法兜底检索。配置 embedding 模型后，系统会增加向量语义召回，并通过 Reciprocal Rank Fusion（RRF）融合语义、BM25 和词法结果。上传的原始文件不会长期保存。

## 能力范围

- Web 入口：`/knowledge`
  - 拖拽或选择一个或多个文档，选择后自动处理。
  - 支持 PDF、DOC、DOCX、TXT、Markdown、RTF、HTML 和 ODT。
  - 自动读取文件名和文档元数据，提取标题、作者与日期。
  - 自动生成摘要、来源类型和投资主题标签。
  - 摘要分类优先复用当前 LiteLLM 模型；模型不可用时回退本地规则，不影响入库。
  - 入库前按正文哈希去重，重复文档不会再次调用模型。
  - 配置语义模型后，新文档自动生成向量；页面显示当前模型和向量覆盖率。
  - 可在页面一键为存量文档构建或更新语义索引。
  - 同页提供检索验证入口，用于检查材料是否可被召回。
- API：
  - `POST /api/v1/rag/documents/upload`：multipart 上传并自动处理文档。
  - `POST /api/v1/rag/documents`：投喂文档。
  - `GET /api/v1/rag/documents`：分页查看文档。
  - `GET /api/v1/rag/documents/{document_id}`：查看文档及 chunk。
  - `DELETE /api/v1/rag/documents/{document_id}`：删除文档及索引。
  - `POST /api/v1/rag/search`：检索相关 chunk。
  - `POST /api/v1/rag/embeddings/rebuild`：为全部或指定文档构建/更新语义向量。
  - `GET /api/v1/rag/stats`：查看文档数、chunk 数和分块参数。
- Agent 工具：
  - `search_investment_knowledge`：按问题、关键词和标签检索投资知识库。
  - `get_investment_knowledge_stats`：查看知识库规模和检索模式。

## RAG 设计原则

1. **先保证可追溯**
   - 每条结果返回 `document_id`、`chunk_id`、标题、来源类型、来源 URI、标签、chunk 序号和检索分数。
   - Agent 使用召回结果时可以引用出处，而不是把偏好直接混进系统 Prompt。

2. **语义、全文和词法混合召回**
   - 默认不依赖外部 embedding 服务，避免私有偏好材料在未授权时离开本地环境。
   - SQLite FTS5 负责 BM25 关键词召回，中文词法兜底使用单字与二元组，降低中文未分词导致的漏召回。
   - 配置 embedding 模型后，文档 chunk 会携带标题、来源类型和标签生成向量；查询只生成一次向量，再与同模型、同维度的 chunk 计算余弦相似度。
   - 三路结果使用 RRF 按排名融合，不直接混加 BM25、词法命中数和余弦分数，避免不同分数尺度互相污染。
   - embedding 请求失败时，入库继续完成，检索明确标记为 `semantic_fallback` 并回退 FTS5/词法结果。

3. **控制上下文污染**
   - 投喂不会自动进入每次分析 Prompt。
   - Agent 需要时通过工具按问题检索，降低无关材料挤占上下文、过期偏好影响结论的风险。

4. **去重和可删除**
   - 文档正文会计算 SHA-256 哈希；默认遇到相同正文时返回已有文档，不重复入库。
   - 文件上传在模型富化前执行去重，避免重复摘要产生额外模型成本。
   - 兼容 JSON API 的 `replace_existing` 参数可替换同正文旧文档。
   - 删除文档会同时清理 chunk 和 FTS 索引。

5. **文件安全边界**
   - 单文件最大 20MB，解析后正文最大 1,000,000 字符。
   - DOCX 和 ODT 会检查压缩成员数与解压后总体积，降低压缩炸弹风险。
   - 文件扩展名与 PDF、DOC、ZIP 文档签名会交叉校验。
   - 解析过程不执行宏、脚本或文档内嵌对象。

## 支持格式

| 格式 | 解析方式 | 说明 |
| --- | --- | --- |
| PDF | `pypdf` | 支持文本型 PDF；扫描件需要先 OCR |
| DOCX | `python-docx` | 解析段落、表格和核心属性 |
| DOC | `antiword` / `catdoc` / LibreOffice / macOS `textutil` | Docker 镜像内置 `antiword` |
| TXT / Markdown | 多编码文本解析 | 支持 UTF-8、UTF-16、GB18030、Big5 |
| RTF | `striprtf` | 提取格式化文本中的正文 |
| HTML | 标准库 HTML parser | 忽略脚本和样式内容 |
| ODT | ZIP + XML | 解析正文、标题和作者 |

## 自动摘要与分类

- 来源类型会归一为 `article`、`news`、`book`、`note`、`preference` 或 `other`。
- 长文不会把全文发送给模型，只截取开头、中段和结尾的代表性文本。
- 模型必须返回结构化摘要、分类和 3-8 个标签；无效输出会回退本地规则。
- 摘要、解析器、原始文件名、富化方式和模型名保存在文档 metadata 中，方便审计。
- 原有 `POST /documents` JSON 接口继续保留，供 Agent、脚本和外部系统显式传入正文。

## 配置项

配置项均为可选，默认即可运行。新增或调整后需要重启后端服务。

```bash
# 单个 chunk 目标字符数，默认 1200，允许范围 300-4000。
RAG_CHUNK_SIZE=1200

# 相邻 chunk 重叠字符数，默认 180，最大不超过 chunk_size 的一半。
RAG_CHUNK_OVERLAP=180

# 默认召回 chunk 数，默认 8，允许范围 1-30。
RAG_DEFAULT_TOP_K=8

# LiteLLM embedding 模型；留空时关闭语义召回。
RAG_EMBEDDING_MODEL=openai/text-embedding-3-small

# OpenAI-compatible embedding 服务可单独指定地址和密钥。
RAG_EMBEDDING_BASE_URL=https://api.openai.com/v1
RAG_EMBEDDING_API_KEY=sk-***

# 可选维度覆盖；0 使用模型默认值。
RAG_EMBEDDING_DIMENSIONS=0

# 批量大小、超时和 SQLite 单次语义扫描上限。
RAG_EMBEDDING_BATCH_SIZE=32
RAG_EMBEDDING_TIMEOUT_SECONDS=30
RAG_SEMANTIC_SCAN_LIMIT=20000
```

`RAG_EMBEDDING_MODEL` 应填写 embedding 模型，不应填写普通聊天/生成模型。远程 embedding 启用后，文档 chunk 和检索问题会发送到对应服务；敏感偏好材料建议使用可信私有服务或本地模型，例如 Ollama 托管的 embedding 模型。

修改模型、服务地址或维度后，重启后端并在 `/knowledge` 页面点击“更新语义索引”。旧模型向量会保留在数据库中，但不会参与新模型检索，重建后会被覆盖。

## 存储位置

RAG 使用项目现有 `DatabaseManager` 和数据库 URL。默认部署通常是 SQLite 数据库；新表包括：

- `rag_documents`：文档级元数据、正文哈希、来源类型、标签、chunk 数。
- `rag_chunks`：chunk 内容、hash、字符数、token 估算、embedding 模型、维度和向量 JSON。
- `rag_chunks_fts`：SQLite FTS5 虚拟表，用于本地全文检索。

当前语义检索适合本地中小规模知识库：SQLite 保存向量，查询时最多扫描 `RAG_SEMANTIC_SCAN_LIMIT` 个当前模型 chunk。若规模增长到数十万 chunk，应迁移到带 ANN 索引的向量数据库；文档与 chunk 契约无需改变。

## 排障

- 投喂失败提示 `content exceeds max length`：单篇正文超过 1,000,000 字符，建议按章节拆分。
- DOC 提示缺少转换器：安装 `antiword`、`catdoc` 或 LibreOffice；macOS 会自动使用系统 `textutil`，也可以将文件另存为 DOCX。
- PDF 没有提取到文本：通常是扫描件或图片型 PDF，需要先做 OCR。
- 自动摘要显示“本地富化”：当前模型未配置、请求失败或返回无效结构，文档仍已正常解析和入库。
- 页面显示“未配置语义模型”：在设置页或 `.env` 中填写 `RAG_EMBEDDING_MODEL`，必要时补充专用 base URL 和 API key，重启后端。
- 语义覆盖率不足 100%：新模型刚启用、模型已切换或部分 embedding 请求失败；点击“更新语义索引”并检查返回的失败数。
- 检索模式包含 `semantic_fallback`：当前没有可用的同模型向量，或查询向量生成失败；系统仍返回 FTS5/词法结果。
- 检索没有结果：先确认知识库中有相关材料；未启用语义检索时，可尝试更短、更接近正文的关键词。
- 删除后仍看到旧结果：刷新 `/knowledge` 页面；若数据库被外部工具修改，重启后端可重建服务实例。

## 回滚

- 功能级回滚：删除本次新增/修改的 RAG 相关代码并重启服务。
- 数据级清理：在确认不需要保留知识库后，备份数据库，再清理 `rag_documents`、`rag_chunks` 和 `rag_chunks_fts`。
- 配置级回滚：移除 `.env` 中 `RAG_EMBEDDING_*` 配置并重启，系统立即回到 FTS5/BM25 + 词法检索；已存向量不会被读取。
