import type React from 'react';
import type { DragEvent, FormEvent } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  BrainCircuit,
  Database,
  FileText,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
} from 'lucide-react';
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
import type {
  RagDocumentCreateResponse,
  RagDocumentItem,
  RagSearchResultItem,
  RagSourceType,
  RagStatsResponse,
} from '../types/rag';
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

type UploadQueueItem = {
  id: string;
  name: string;
  status: 'pending' | 'uploading' | 'success' | 'error';
  result?: RagDocumentCreateResponse;
  error?: string;
};

const KnowledgeBasePage: React.FC = () => {
  useEffect(() => {
    document.title = '投资知识库 - DSA';
  }, []);

  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<UploadQueueItem[]>([]);
  const [ingestError, setIngestError] = useState<ParsedApiError | null>(null);

  const [stats, setStats] = useState<RagStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<ParsedApiError | null>(null);
  const [embeddingLoading, setEmbeddingLoading] = useState(false);
  const [embeddingMessage, setEmbeddingMessage] = useState('');

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

  const handleRebuildEmbeddings = async () => {
    if (!stats?.semanticEnabled || embeddingLoading) return;
    setEmbeddingLoading(true);
    setEmbeddingMessage('');
    setStatsError(null);
    try {
      const response = await ragApi.rebuildEmbeddings();
      if (response.failedChunks > 0) {
        setEmbeddingMessage(
          `已更新 ${response.updatedChunks} 个 chunk，${response.failedChunks} 个失败：${response.error || '请检查 embedding 服务配置'}`,
        );
      } else {
        setEmbeddingMessage(
          `语义索引已更新：新增 ${response.updatedChunks} 个，跳过 ${response.skippedChunks} 个。`,
        );
      }
      await loadStats();
    } catch (error) {
      setStatsError(getParsedApiError(error));
    } finally {
      setEmbeddingLoading(false);
    }
  };

  const handleFiles = async (files: File[]) => {
    if (!files.length || uploadLoading) return;
    const accepted = files.filter((file) => file.size > 0);
    if (!accepted.length) {
      setIngestError({
        title: '没有可上传的文档',
        message: '请选择非空的 PDF、Word 或文本文件。',
        rawMessage: 'no non-empty files selected',
        category: 'missing_params',
      });
      return;
    }

    const queueItems = accepted.map((file, index) => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
      name: file.name,
      status: 'pending' as const,
    }));
    setUploadQueue(queueItems);
    setUploadLoading(true);
    setIngestError(null);

    for (let index = 0; index < accepted.length; index += 1) {
      const file = accepted[index];
      const itemId = queueItems[index].id;
      setUploadQueue((items) => items.map((item) => (
        item.id === itemId ? { ...item, status: 'uploading' } : item
      )));
      try {
        const result = await ragApi.uploadDocument(file);
        setUploadQueue((items) => items.map((item) => (
          item.id === itemId ? { ...item, status: 'success', result } : item
        )));
      } catch (error) {
        const parsedError = getParsedApiError(error);
        setUploadQueue((items) => items.map((item) => (
          item.id === itemId
            ? { ...item, status: 'error', error: parsedError.message }
            : item
        )));
      }
    }

    setUploadLoading(false);
    setDocumentsPage(1);
    await Promise.all([loadStats(), loadDocuments()]);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    void handleFiles(Array.from(event.dataTransfer.files));
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
        description="上传投资文章、新闻、研究报告和书籍文档；系统自动解析正文、生成摘要、识别分类与标签，并建立可追溯的本地检索索引。"
        actions={(
          <>
            <Button
              variant="secondary"
              disabled={!stats?.semanticEnabled || (stats?.chunkCount ?? 0) === 0}
              isLoading={embeddingLoading}
              loadingText="构建中..."
              onClick={() => void handleRebuildEmbeddings()}
            >
              <BrainCircuit className="h-4 w-4" />
              更新语义索引
            </Button>
            <Button variant="secondary" onClick={() => void refreshAll()}>
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
          </>
        )}
      />

      <InlineAlert
        title="只需上传文档"
        message="无需填写标题、来源或标签。系统会从文件名和文档元数据识别标题，自动完成正文解析、摘要、分类、标签、去重和分块；原始文件不会长期保存。"
        variant="info"
      />

      {statsError ? <ApiErrorAlert error={statsError} onDismiss={() => setStatsError(null)} /> : null}
      {embeddingMessage ? (
        <InlineAlert
          title="语义索引"
          message={embeddingMessage}
          variant={embeddingMessage.includes('失败') ? 'warning' : 'success'}
        />
      ) : null}
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
          value={stats?.semanticEnabled ? 'Hybrid' : 'FTS5'}
          hint={stats?.semanticEnabled
            ? `语义覆盖 ${stats.embeddingCoveragePct.toFixed(1)}% · ${stats.embeddingModel}`
            : '未配置语义模型，使用 FTS5 + 词法检索'}
          tone="default"
          icon={<BrainCircuit className="h-5 w-5" />}
        />
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <Card title="上传文档" subtitle="Upload" className="xl:sticky xl:top-4">
          {ingestError ? <ApiErrorAlert error={ingestError} onDismiss={() => setIngestError(null)} /> : null}
          <div
            className={`flex min-h-[250px] flex-col items-center justify-center rounded-2xl border border-dashed p-6 text-center transition-colors ${
              isDragging
                ? 'border-primary bg-primary/10'
                : 'border-border/70 bg-card/45 hover:border-primary/60 hover:bg-hover/45'
            } ${uploadLoading ? 'cursor-wait opacity-70' : 'cursor-pointer'}`}
            role="button"
            tabIndex={0}
            onClick={() => {
              if (!uploadLoading) uploadInputRef.current?.click();
            }}
            onKeyDown={(event) => {
              if (!uploadLoading && (event.key === 'Enter' || event.key === ' ')) {
                uploadInputRef.current?.click();
              }
            }}
            onDragOver={(event) => {
              event.preventDefault();
              if (!uploadLoading) setIsDragging(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setIsDragging(false);
            }}
            onDrop={handleDrop}
          >
            <div className="rounded-2xl bg-primary/10 p-4 text-primary">
              <UploadCloud className="h-8 w-8" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-foreground">拖拽文档到这里</h3>
            <p className="mt-2 text-sm leading-6 text-secondary-text">
              或点击选择一个或多个文件，选择后自动开始解析和入库。
            </p>
            <p className="mt-3 text-xs leading-5 text-muted-text">
              {(stats?.supportedExtensions?.length
                ? stats.supportedExtensions
                : ['.pdf', '.doc', '.docx', '.txt', '.md', '.rtf', '.html', '.odt'])
                .join(' / ')}
              {' · '}
              单文件不超过 {stats?.maxUploadMb ?? 20}MB
            </p>
            <input
              ref={uploadInputRef}
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.txt,.md,.markdown,.rtf,.html,.htm,.odt"
              className="hidden"
              disabled={uploadLoading}
              onChange={(event) => {
                void handleFiles(Array.from(event.target.files ?? []));
                event.target.value = '';
              }}
            />
          </div>

          {uploadQueue.length > 0 ? (
            <div className="mt-4 space-y-3">
              {uploadQueue.map((item) => (
                <UploadResultCard key={item.id} item={item} />
              ))}
            </div>
          ) : (
            <p className="mt-4 text-xs leading-5 text-secondary-text">
              摘要与分类优先使用当前已配置的 AI 模型；语义模型配置后会为新文档自动建立向量索引。
              任一模型不可用时仍可完成文档入库，并继续使用全文与词法检索。
            </p>
          )}
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
                      {document.summary ? (
                        <p className="mt-3 text-sm leading-6 text-foreground/90">{document.summary}</p>
                      ) : null}
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

const UploadResultCard: React.FC<{ item: UploadQueueItem }> = ({ item }) => {
  const statusLabel = {
    pending: '等待处理',
    uploading: '解析与分类中',
    success: item.result?.duplicate ? '已去重' : '已入库',
    error: '处理失败',
  }[item.status];
  const statusVariant = item.status === 'error'
    ? 'danger'
    : item.status === 'success'
      ? 'success'
      : 'warning';

  return (
    <article className="rounded-2xl border border-border/60 bg-card/70 p-4 shadow-soft-card">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-2 text-primary">
          <FileText className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-foreground">{item.name}</h3>
            <Badge variant={statusVariant}>{statusLabel}</Badge>
          </div>
          {item.status === 'uploading' ? (
            <p className="mt-2 text-xs leading-5 text-secondary-text">
              正在提取正文并自动生成摘要、分类和标签...
            </p>
          ) : null}
          {item.error ? (
            <p className="mt-2 text-sm leading-5 text-danger">{item.error}</p>
          ) : null}
          {item.result ? (
            <>
              <p className="mt-2 text-sm font-medium text-foreground">{item.result.title}</p>
              {item.result.summary ? (
                <p className="mt-2 text-xs leading-5 text-secondary-text">{item.result.summary}</p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="info">
                  {SOURCE_TYPE_LABEL[item.result.sourceType] ?? item.result.sourceType}
                </Badge>
                <Badge>{item.result.chunkCount} chunks</Badge>
                {item.result.parser ? <Badge>{item.result.parser}</Badge> : null}
                {item.result.enrichmentMethod ? (
                  <Badge variant="history">
                    {item.result.enrichmentMethod === 'llm' ? 'AI 富化' : '本地富化'}
                  </Badge>
                ) : null}
              </div>
              {item.result.tags.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {item.result.tags.map((tag) => <Badge key={tag} variant="history">#{tag}</Badge>)}
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </article>
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
