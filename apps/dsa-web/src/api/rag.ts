import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  RagDeleteResponse,
  RagDocumentCreateRequest,
  RagDocumentCreateResponse,
  RagDocumentDetail,
  RagDocumentListQuery,
  RagDocumentListResponse,
  RagSearchRequest,
  RagSearchResponse,
  RagStatsResponse,
} from '../types/rag';

function toDocumentPayload(payload: RagDocumentCreateRequest): Record<string, unknown> {
  return {
    title: payload.title,
    content: payload.content,
    source_type: payload.sourceType,
    source_uri: payload.sourceUri,
    author: payload.author,
    published_at: payload.publishedAt,
    tags: payload.tags,
    metadata: payload.metadata ?? {},
    replace_existing: payload.replaceExisting ?? false,
  };
}

function toListParams(query: RagDocumentListQuery = {}): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (query.page !== undefined) params.page = query.page;
  if (query.pageSize !== undefined) params.page_size = query.pageSize;
  if (query.sourceType) params.source_type = query.sourceType;
  if (query.query) params.query = query.query;
  return params;
}

function toSearchPayload(payload: RagSearchRequest): Record<string, unknown> {
  return {
    query: payload.query,
    top_k: payload.topK,
    tags: payload.tags,
  };
}

export const ragApi = {
  async createDocument(payload: RagDocumentCreateRequest): Promise<RagDocumentCreateResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/rag/documents', toDocumentPayload(payload));
    return toCamelCase<RagDocumentCreateResponse>(response.data);
  },

  async listDocuments(query: RagDocumentListQuery = {}): Promise<RagDocumentListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/rag/documents', {
      params: toListParams(query),
    });
    return toCamelCase<RagDocumentListResponse>(response.data);
  },

  async getDocument(documentId: number): Promise<RagDocumentDetail> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/rag/documents/${documentId}`);
    return toCamelCase<RagDocumentDetail>(response.data);
  },

  async deleteDocument(documentId: number): Promise<RagDeleteResponse> {
    const response = await apiClient.delete<Record<string, unknown>>(`/api/v1/rag/documents/${documentId}`);
    return toCamelCase<RagDeleteResponse>(response.data);
  },

  async search(payload: RagSearchRequest): Promise<RagSearchResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/rag/search', toSearchPayload(payload));
    return toCamelCase<RagSearchResponse>(response.data);
  },

  async getStats(): Promise<RagStatsResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/rag/stats');
    return toCamelCase<RagStatsResponse>(response.data);
  },
};
