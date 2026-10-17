export type SourceRef = { source_id: string; version_id: string };
export type EvidenceRef = SourceRef & {
  chunk_id: string;
  title: string;
  locator: {
    page?: number;
    paragraph?: number;
    row_start?: number;
    row_end?: number;
  };
};
export type SourceSummary = {
  id: string;
  title: string;
  type: string;
  author: string;
  updated_at: string;
  current_version_id?: string | null;
  classification?: string;
  department_id?: string;
  processing_status?: string;
  source_revision?: number;
  revision?: number;
  excerpt?: string;
};
export type SourceChunk = {
  id?: string;
  chunk_id?: string;
  text?: string;
  content?: string;
  locator?: EvidenceRef["locator"];
};
export type SourceDetail = SourceSummary & {
  chunks?: SourceChunk[];
  provenance?: Record<string, unknown>;
  versions?: {
    id?: string;
    version_id?: string;
    number?: number;
    processing_status?: string;
  }[];
  link_proposals?: {
    id: string;
    source_id?: string;
    target_id?: string;
    relation?: string;
    status?: string;
  }[];
};
