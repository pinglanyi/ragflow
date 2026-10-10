import { Button } from '@/components/ui/button';
import message from '@/components/ui/message';
import { GenerateType } from '@/constants/knowledge';
import {
  DatasetGenerateKeys,
  useTraceRunData,
} from '@/hooks/use-dataset-generate';
import { compileExistingChunks } from '@/services/knowledge-service';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';

export function CompileExistingButton({ enabled }: { enabled: boolean }) {
  const { id } = useParams();
  const { t } = useTranslation();
  const client = useQueryClient();
  const { data: trace } = useTraceRunData(GenerateType.KnowledgeGraph);
  const running =
    trace?.progress != null && trace.progress >= 0 && trace.progress < 1;
  const { mutate, isPending } = useMutation({
    mutationFn: async () => {
      const { data } = await compileExistingChunks(id!);
      if (data.code !== 0)
        throw new Error(data.message || t('message.compileNotSupported'));
      return data;
    },
    onSuccess: () => {
      message.success(t('message.operated'));
      for (const type of [
        GenerateType.KnowledgeGraph,
        GenerateType.MindMap,
        GenerateType.Timeline,
      ]) {
        client.invalidateQueries({
          queryKey: DatasetGenerateKeys.traceById(type, id),
        });
      }
    },
    onError: (error: Error) => message.error(error.message),
  });
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="outline"
        loading={isPending}
        disabled={!enabled || !id || running}
        onClick={() => mutate()}
      >
        {t('knowledgeCompilation.compileExistingChunks')}
      </Button>
      <span className="text-xs text-text-secondary">
        {t('knowledgeCompilation.compileExistingChunksHint')}
      </span>
    </div>
  );
}
