import { Button } from '@/components/ui/button';
import { DatasetNavKeys } from '@/hooks/use-dataset-nav-request';
import { useKnowledgeBaseId } from '@/hooks/use-knowledge-request';
import { DatasetNavNode } from '@/interfaces/database/dataset-nav';
import datasetNavService from '@/services/dataset-nav-service';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SelectedNavNode } from './hooks/use-compilation-nav';

export function NavNodeEditor({
  node,
  onSaved,
}: {
  node: SelectedNavNode;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const kbId = useKnowledgeBaseId();
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(node.displayName || node.name);
  const [description, setDescription] = useState(node.description);
  // Empty means unchanged: the displayed parent in two-layer mode may differ
  // from the real parent. Never infer the stored parent from the projection.
  const [parent, setParent] = useState('');
  const targets = useQuery({
    queryKey: DatasetNavKeys.targets(kbId),
    enabled: editing && !!kbId,
    retry: false,
    queryFn: async (): Promise<DatasetNavNode[]> => {
      const { data } = await datasetNavService.getNavTargets(kbId);
      if (data?.code !== 0)
        throw new Error(
          data?.message || t('knowledgeCompilation.navLoadFailed'),
        );
      return data.data.items;
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      const { data } = await datasetNavService.updateNavNode(kbId, node.name, {
        display_name: label,
        description,
        ...(parent ? { parent_name: parent } : {}),
      });
      if (data?.code !== 0)
        throw new Error(
          data?.message || t('knowledgeCompilation.navEditFailed'),
        );
    },
    onSuccess: onSaved,
  });
  if (!editing)
    return (
      <Button variant="outline" onClick={() => setEditing(true)}>
        {t('knowledgeCompilation.navEditMove')}
      </Button>
    );
  const fieldClass =
    'w-full rounded-md border border-border-button bg-bg-base text-text-primary p-2';
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label className="block space-y-1">
        <span>{t('knowledgeCompilation.navDisplayName')}</span>
        <input
          className={fieldClass}
          required
          maxLength={200}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
      </label>
      <label className="block space-y-1">
        <span>{t('knowledgeCompilation.description')}</span>
        <textarea
          className={fieldClass}
          maxLength={20000}
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      <label className="block space-y-1">
        <span>{t('knowledgeCompilation.navMoveTo')}</span>
        <select
          className={fieldClass}
          value={parent}
          onChange={(event) => setParent(event.target.value)}
          disabled={targets.isFetching}
        >
          <option value="">{t('knowledgeCompilation.navKeepParent')}</option>
          {!node.docId && (
            <option value="root">{t('knowledgeCompilation.navRoot')}</option>
          )}
          {targets.data
            ?.filter((target) => target.name !== node.name)
            .map((target) => (
              <option key={target.name} value={target.name}>
                {target.display_name || target.name} — {target.name}
              </option>
            ))}
        </select>
      </label>
      <p className="text-xs text-text-secondary">
        {t('knowledgeCompilation.navEditHint')}
      </p>
      {(targets.error || save.error) && (
        <p role="alert">{(save.error || targets.error)?.message}</p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || !label.trim()}>
          {t('knowledgeCompilation.navSave')}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={save.isPending}
          onClick={() => setEditing(false)}
        >
          {t('knowledgeCompilation.navCancel')}
        </Button>
      </div>
    </form>
  );
}
