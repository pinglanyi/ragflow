import { IDataset } from '@/interfaces/database/dataset';

export function canGenerateWiki(knowledgeBase?: IDataset, requirePipeline = true): boolean {
  return (
    (knowledgeBase?.chunk_count ?? 0) > 0 &&
    (!requirePipeline || Boolean(knowledgeBase?.pipeline_id?.trim()))
  );
}
