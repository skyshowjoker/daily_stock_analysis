import type React from 'react';
import type { FormEvent } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, Database, RefreshCw, Search, Trash2, UploadCloud } from 'lucide-react';
import { ragApi } from '../api/rag';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  EmptyState,
  InlineAlert,
  Input,
  Loading,
  PageHeader,
  Select,
  StatCard,
} from '../components/common';
import type { RagDocumentItem, RagSearchResultItem, RagSourceType, RagStatsResponse } from '../types/rag';
import { formatDateTime } from '../utils/format';

const PAGE_SIZE = 20;

const SOURCE_TYPE_OPTIONS: Array<{ value: RagSourceType | ''; label: string }> = [
  { value: '', label: '全部来源' },
  { value: 'article', label: '文章' },
  { value: 'news', label: '新闻' },
  { value: 'book', label: '书籍/摘录' },
  { value: 'note', label: '笔记' },
  { value: 'preference', label: '个人偏好' },
  { value: 'url', label: '网页资料' },
  { value: 'other', label: '其他' },
];

const INGEST_SOURCE_OPTIONS = SOURCE_TYPE_OPTIONS.filter((option) => option.value !== '') as Array<{
  value: RagSourceType;
  label: string;
}>;

const SOURCE_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  INGEST_SOURCE_OPTIONS.map((option) => [option.value, option.label]),
);

function parseTags(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[,\n，、#]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      if (seen.has(item)) return false;
      seen.add(item);
      return true;
    })
    .slice(0, 20);
}

function formatScore(value: number): string {
  if (!Number.isFinite(value)) return '0.000';
  return value.toFixed(3);
}

const KnowledgeBasePage: React.FC = () => {
  useEffect(() => {
    document.title = '投资知识库 - DSA';
  }, []);

  const [title, setTitle] = useState('');
  const [sourceType, setSourceType] = useState<RagSourceType>('article');
  const [sourceUri, setSourceUri] = useState('');
  const [author, setAuthor] = useState('');
  const [publishedAt, setPublishedAt] = useState('');
  const [tagInput, setTagInput] = useState('投资框架');
  const [content, setContent] = useState('');
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [ingestLoading, setIngestLoading] = useState(false);
  const [ingestError, setIngestError] = useState<ParsedApiError | null>(null);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);

  const [stats, setStats] = useState<RagStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<ParsedApiError | null>(null);

  const [documents, setDocuments] = useState<RagDocumentItem[]>([]);
  const [documentsTotal, setDocumentsTotal] = useState(0);
  const [documentsPage, setDocumentsPage] = useState(1);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState<ParsedApiError | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<number | null>(null);
  const [documentQueryDraft, setDocumentQueryDraft] = useState('');
  const [sourceFilterDraft, setSourceFilterDraft] = useState('');
  const [documentFilters, setDocumentFilters] = useState({ query: '', sourceType: '' });

  const [searchQuery, setSearchQuery] = useState('');
  const [searchTags, setSearchTags] = useState('');
  const [searchResults, setSearchResults] = useState<RagSearchResultItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<ParsedApiError | null>(null);
  const [searchMode, setSearchMode] = useState('');
  const [searchRan, setSearchRan] = useState(false);

  const totalPages = Math.max(1, Math.ceil(documentsTotal / PAGE_SIZE));
  const parsedTags = useMemo(() => parseTags(tagInput), [tagInput]);

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const response = await ragApi.getStats();
      setStats(response);
      setStatsError(null);
    } catch (error) {
      setStatsError(getParsedApiError(error));
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const loadDocuments = useCallback(async () => {
    setDocumentsLoading(true);
    try {
      const response = await ragApi.listDocuments({
        page: documentsPage,
        pageSize: PAGE_SIZE,
        query: documentFilters.query || undefined,
        sourceType: documentFilters.sourceType || undefined,
      });
      setDocuments(response.items);
      setDocumentsTotal(response.total);
      setDocumentsError(null);
    } catch (error) {
      setDocumentsError(getParsedApiError(error));
    } finally {
      setDocumentsLoading(false);
    }
  }, [documentFilters, documentsPage]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const refreshAll = async () => {
    await Promise.all([loadStats(), loadDocuments()]);
  };

  const handleIngest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedTitle = title.trim();
    const trimmedContent = content.trim();
    if (!trimmedTitle || !trimmedContent) {
      setIngestError({
        title: '投喂内容不完整',
        message: '标题和正文都是必填项。',
        rawMessage: 'title and content are required',
        category: 'missing_params',
      });
      return;
    }

    setIngestLoading(true);
    setIngestError(null);
    setIngestMessage(null);
    try {
      const response = await ragApi.createDocument({
        title: trimmedTitle,
        content: trimmedContent,
        sourceType,
        sourceUri: sourceUri.trim() || undefined,
        author: author.trim() || undefined,
        publishedAt: publishedAt || undefined,
        tags: parsedTags,
        metadata: { ingested_from: 'web' },
        replaceExisting,
      });
      setIngestMessage(
        response.duplicate
          ? `已有相同正文，未重复入库：#${response.documentId}「${response.title}」`
          : `已入库 #${response.documentId}「${response.title}」，生成 ${response.chunkCount} 个 chunk。`,
      );
      setDocumentsPage(1);
      await Promise.all([loadStats(), loadDocuments()]);
    } catch (error) {
      setIngestError(getParsedApiError(error));
    } finally {
      setIngestLoading(false);
    }
  };

  const handleApplyDocumentFilters = () => {
    setDocumentsPage(1);
    setDocumentFilters({
      query: documentQueryDraft.trim(),
      sourceType: sourceFilterDraft,
    });
  };

  const handleSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) {
      setSearchError({
        title: '检索问题为空',
        message: '请输入要检索的投资问题、关键词或偏好约束。',
        rawMessage: 'query is required',
        category: 'missing_params',
      });
      return;
    }

    setSearchLoading(true);
    setSearchError(null);
    setSearchRan(true);
    try {
      const response = await ragApi.search({
        query,
        topK: 8,
        tags: parseTags(searchTags),
      });
      setSearchResults(response.results);
      setSearchMode(response.retrievalMode);
    } catch (error) {
      setSearchError(getParsedApiError(error));
    } finally {
      setSearchLoading(false);
    }
  };

  const handleDeleteDocument = async (document: RagDocumentItem) => {
    const confirmed = window.confirm(`确认删除「${document.title}」及其所有 chunk 吗？`);
    if (!confirmed) return;
    setDeletingDocumentId(document.id);
    setDocumentsError(null);
    try {
      await ragApi.deleteDocument(document.id);
      await Promise.all([loadStats(), loadDocuments()]);
    } catch (error) {
      setDocumentsError(getParsedApiError(error));
    } finally {
      setDeletingDocumentId(null);
    }
  };

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="Investment RAG"
        title="投资知识库"
        description="沉淀投资文章、新闻、书籍摘录和个人偏好；投喂后自动去重、分块、建立本地检索索引，并向 Agent 暴露可追溯的知识召回工具。"
        actions={(
          <Button variant="secondary" onClick={() => void refreshAll()}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        )}
      />

      <InlineAlert
        title="RAG 最佳实践默认策略"
        message="当前入口只保存你明确提交的正文，来源 URL 仅用于溯源，不会自动抓网页。检索结果会保留 title、source、tag、chunk 和 score，方便你判断召回是否可信。"
        variant="info"
      />

      {statsError ? <ApiErrorAlert error={statsError} onDismiss={() => setStatsError(null)} /> : null}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Documents"
          value={statsLoading && !stats ? '...' : stats?.documentCount ?? 0}
          hint="已入库材料"
          icon={<Database className="h-5 w-5" />}
          tone="primary"
        />
        <StatCard
          label="Chunks"
          value={statsLoading && !stats ? '...' : stats?.chunkCount ?? 0}
          hint="可检索片段"
          icon={<BookOpen className="h-5 w-5" />}
          tone="success"
        />
        <StatCard
          label="Chunk Size"
          value={stats?.chunkSize ?? 1200}
          hint={`Overlap ${stats?.chunkOverlap ?? 180}`}
          tone="warning"
        />
        <StatCard
          label="Retrieval"
          value="FTS5"
          hint={stats?.retrievalMode ?? 'sqlite_fts5_bm25_lexical'}
          tone="default"
        />
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <Card title="投喂知识" subtitle="Ingest" className="xl:sticky xl:top-4">
          {ingestError ? <ApiErrorAlert error={ingestError} onDismiss={() => setIngestError(null)} /> : null}
          {ingestMessage ? (
            <InlineAlert
              title="投喂完成"
              message={ingestMessage}
              variant="success"
              className="mb-4"
              action={(
                <button type="button" className="text-sm underline" onClick={() => setIngestMessage(null)}>
                  关闭
                </button>
              )}
            />
          ) : null}
          <form className="space-y-4" onSubmit={handleIngest}>
            <Input
              label="标题"
              placeholder="如：巴菲特致股东信 2023 摘录"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Select
                label="来源类型"
                value={sourceType}
                onChange={(value) => setSourceType(value as RagSourceType)}
                options={INGEST_SOURCE_OPTIONS}
              />
              <Input
                label="作者/来源"
                placeholder="可选"
                value={author}
                onChange={(event) => setAuthor(event.target.value)}
              />
            </div>
            <Input
              label="来源 URL / 书籍定位"
              hint="仅作溯源，不会自动抓取网页正文。"
              placeholder="https://... 或 book://..."
              value={sourceUri}
              onChange={(event) => setSourceUri(event.target.value)}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="发布日期"
                type="date"
                value={publishedAt}
                onChange={(event) => setPublishedAt(event.target.value)}
              />
              <Input
                label="标签"
                hint={`已识别 ${parsedTags.length} 个标签`}
                placeholder="价值投资, 风险, 偏好"
                value={tagInput}
                onChange={(event) => setTagInput(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="rag-content" className="mb-2 block text-sm font-medium text-foreground">
                正文
              </label>
              <textarea
                id="rag-content"
                className="input-surface input-focus-glow min-h-[260px] w-full resize-y rounded-xl border bg-transparent px-4 py-3 text-sm leading-6 text-foreground transition-all focus:outline-none"
                placeholder="粘贴文章、新闻、书籍摘录，或写下你的投资偏好与约束..."
                value={content}
                onChange={(event) => setContent(event.target.value)}
              />
              <p className="mt-2 text-xs text-secondary-text">
                {content.trim().length.toLocaleString()} 字符；上限 1,000,000 字符。
              </p>
            </div>
            <label className="flex items-start gap-3 rounded-xl border border-border/55 bg-card/50 p-3 text-sm text-secondary-text">
              <input
                type="checkbox"
                className="mt-1"
                checked={replaceExisting}
                onChange={(event) => setReplaceExisting(event.target.checked)}
              />
              <span>
                如果正文哈希已存在，替换旧文档。默认会去重并返回已有文档，避免同一材料重复污染召回。
              </span>
            </label>
            <Button type="submit" className="w-full" isLoading={ingestLoading} loadingText="正在入库...">
              <UploadCloud className="h-4 w-4" />
              投喂到知识库
            </Button>
          </form>
        </Card>

        <div className="space-y-5">
          <Card title="检索验证" subtitle="Retrieve">
            {searchError ? <ApiErrorAlert error={searchError} onDismiss={() => setSearchError(null)} /> : null}
            <form className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px_auto]" onSubmit={handleSearch}>
              <Input
                label="问题 / 关键词"
                placeholder="如：我的止损纪律是什么？"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              <Input
                label="标签过滤"
                placeholder="可选，如 risk, preference"
                value={searchTags}
                onChange={(event) => setSearchTags(event.target.value)}
              />
              <div className="flex items-end">
                <Button type="submit" className="w-full" isLoading={searchLoading} loadingText="检索中...">
                  <Search className="h-4 w-4" />
                  检索
                </Button>
              </div>
            </form>
            {searchMode ? (
              <p className="mt-3 text-xs text-secondary-text">检索模式：{searchMode}</p>
            ) : null}
            <div className="mt-4 space-y-3">
              {searchLoading ? <Loading label="正在检索知识库..." /> : null}
              {!searchLoading && searchRan && searchResults.length === 0 ? (
                <EmptyState
                  title="没有召回结果"
                  description="可以换一个问题，或先投喂带有相近标签和关键词的材料。"
                  icon={<Search className="h-8 w-8" />}
                />
              ) : null}
              {!searchLoading && searchResults.map((result) => (
                <SearchResultCard key={result.chunkId} result={result} />
              ))}
            </div>
          </Card>

          <Card title="已入库材料" subtitle="Documents">
            {documentsError ? <ApiErrorAlert error={documentsError} onDismiss={() => setDocumentsError(null)} /> : null}
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_auto]">
              <Input
                label="标题 / 标签 / 来源筛选"
                placeholder="搜索已入库材料"
                value={documentQueryDraft}
                onChange={(event) => setDocumentQueryDraft(event.target.value)}
              />
              <Select
                label="来源类型"
                value={sourceFilterDraft}
                onChange={setSourceFilterDraft}
                options={SOURCE_TYPE_OPTIONS}
              />
              <div className="flex items-end">
                <Button variant="secondary" className="w-full" onClick={handleApplyDocumentFilters}>
                  筛选
                </Button>
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {documentsLoading ? <Loading label="正在加载文档..." /> : null}
              {!documentsLoading && documents.length === 0 ? (
                <EmptyState
                  title="知识库还是空的"
                  description="先从左侧投喂一篇文章、一条新闻、一本书的摘录，或者一条明确的个人投资偏好。"
                  icon={<Database className="h-8 w-8" />}
                />
              ) : null}
              {!documentsLoading && documents.map((document) => (
                <article key={document.id} className="rounded-2xl border border-border/60 bg-card/70 p-4 shadow-soft-card">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-foreground">{document.title}</h3>
                        <Badge variant="info">{SOURCE_TYPE_LABEL[document.sourceType] ?? document.sourceType}</Badge>
                        <Badge>{document.chunkCount} chunks</Badge>
                      </div>
                      <p className="mt-2 text-sm text-secondary-text">
                        {document.author ? `${document.author} · ` : ''}
                        {formatDateTime(document.createdAt)}
                        {document.sourceUri ? ` · ${document.sourceUri}` : ''}
                      </p>
                      {document.tags.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {document.tags.map((tag) => <Badge key={tag} variant="history">#{tag}</Badge>)}
                        </div>
                      ) : null}
                    </div>
                    <Button
                      variant="danger-subtle"
                      size="sm"
                      isLoading={deletingDocumentId === document.id}
                      loadingText="删除中"
                      onClick={() => void handleDeleteDocument(document)}
                    >
                      <Trash2 className="h-4 w-4" />
                      删除
                    </Button>
                  </div>
                </article>
              ))}
            </div>

            {documentsTotal > PAGE_SIZE ? (
              <div className="mt-4 flex items-center justify-between gap-3 text-sm text-secondary-text">
                <span>
                  第 {documentsPage} / {totalPages} 页，共 {documentsTotal} 条
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={documentsPage <= 1}
                    onClick={() => setDocumentsPage((page) => Math.max(1, page - 1))}
                  >
                    上一页
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={documentsPage >= totalPages}
                    onClick={() => setDocumentsPage((page) => Math.min(totalPages, page + 1))}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        </div>
      </div>
    </AppPage>
  );
};

const SearchResultCard: React.FC<{ result: RagSearchResultItem }> = ({ result }) => {
  return (
    <article className="rounded-2xl border border-border/60 bg-card/70 p-4 shadow-soft-card">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-foreground">{result.title}</h3>
            <Badge variant="info">{SOURCE_TYPE_LABEL[result.sourceType] ?? result.sourceType}</Badge>
            <Badge>chunk #{result.chunkIndex + 1}</Badge>
          </div>
          <p className="mt-2 text-xs text-secondary-text">
            score {formatScore(result.score)} · {result.retrieval}
            {result.sourceUri ? ` · ${result.sourceUri}` : ''}
          </p>
        </div>
        <Badge variant="success">doc #{result.documentId}</Badge>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-foreground">{result.content}</p>
      {result.tags.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {result.tags.map((tag) => <Badge key={tag} variant="history">#{tag}</Badge>)}
        </div>
      ) : null}
    </article>
  );
};

export default KnowledgeBasePage;
