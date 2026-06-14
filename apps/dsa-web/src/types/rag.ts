export type RagSourceType = 'article' | 'news' | 'book' | 'note' | 'preference' | 'url' | 'other';

export interface RagDocumentCreateRequest {
  title: string;
  content: string;
  sourceType: RagSourceType;
  sourceUri?: string;
  author?: string;
  publishedAt?: string;
  tags: string[];
  metadata?: Record<string, unknown>;
  replaceExisting?: boolean;
}

export interface RagDocumentCreateResponse {
  documentId: number;
  title: string;
  chunkCount: number;
  duplicate: boolean;
  summary: string;
  sourceType: RagSourceType | string;
  tags: string[];
  enrichmentMethod: string;
  parser: string;
}

export interface RagDocumentItem {
  id: number;
  title: string;
  sourceType: RagSourceType | string;
  sourceUri: string;
  author: string;
  publishedAt?: string | null;
  tags: string[];
  summary: string;
  metadata: Record<string, unknown>;
  contentHash: string;
  status: string;
  chunkCount: number;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface RagDocumentListResponse {
  items: RagDocumentItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface RagDocumentListQuery {
  page?: number;
  pageSize?: number;
  sourceType?: string;
  query?: string;
}

export interface RagChunkItem {
  id: number;
  documentId: number;
  chunkIndex: number;
  content: string;
  charCount: number;
  tokenEstimate: number;
  metadata: Record<string, unknown>;
}

export interface RagDocumentDetail extends RagDocumentItem {
  chunks: RagChunkItem[];
}

export interface RagSearchRequest {
  query: string;
  topK: number;
  tags: string[];
}

export interface RagSearchResultItem {
  chunkId: number;
  documentId: number;
  chunkIndex: number;
  title: string;
  sourceType: RagSourceType | string;
  sourceUri: string;
  tags: string[];
  content: string;
  score: number;
  retrieval: string;
  scoreComponents: Record<string, number>;
  createdAt?: string | null;
}

export interface RagSearchResponse {
  query: string;
  topK: number;
  results: RagSearchResultItem[];
  retrievalMode: string;
}

export interface RagStatsResponse {
  documentCount: number;
  chunkCount: number;
  chunkSize: number;
  chunkOverlap: number;
  retrievalMode: string;
  bySourceType: Record<string, number>;
  supportedExtensions: string[];
  maxUploadMb: number;
  autoEnrichment: boolean;
  semanticEnabled: boolean;
  embeddingModel: string;
  embeddedChunkCount: number;
  embeddingCoveragePct: number;
}

export interface RagEmbeddingRebuildRequest {
  documentId?: number;
  force?: boolean;
}

export interface RagEmbeddingRebuildResponse {
  enabled: boolean;
  embeddingModel: string;
  updatedChunks: number;
  skippedChunks: number;
  failedChunks: number;
  error: string;
}

export interface RagDeleteResponse {
  deleted: number;
}
