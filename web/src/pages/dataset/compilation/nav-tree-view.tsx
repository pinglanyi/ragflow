import { Card } from '@/components/ui/card';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { useTranslation } from 'react-i18next';
import { DatasetNavKeys } from '@/hooks/use-dataset-nav-request';
import { useFetchKnowledgeBaseConfiguration } from '@/hooks/use-knowledge-request';
import {
  GenerateStatus,
  GenerateType,
} from '@/pages/dataset/dataset/generate-button/constants';
import { useTraceRunData } from '@/pages/dataset/dataset/generate-button/hook';
import { useGenerateStatus } from '@/pages/dataset/dataset/generate-button/use-generate-status';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useParams } from 'react-router';

import CompilationEmptyState from './empty-state';
import { useCompilationNav } from './hooks/use-compilation-nav';
import { CompilationLoadingCard } from './loading-card';
import { NavTreeLeftPanel } from './nav-tree-left-panel';

export function NavTreeView() {
  const { t } = useTranslation();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const { data: knowledgeBase } = useFetchKnowledgeBaseConfiguration();
  const { data: skillRunData } = useTraceRunData(GenerateType.ToSkills);
  const { status: skillStatus } = useGenerateStatus(skillRunData);
  const {
    navList,
    navLoading,
    childrenMap,
    selectedNode,
    deleteNavLoading,
    deleteNodeLoading,
    handleParentClick,
    handleChildClick,
    handleDeleteAll,
    handleDeleteNode,
  } = useCompilationNav();

  useEffect(() => {
    if (skillStatus === GenerateStatus.completed && id) {
      queryClient.invalidateQueries({ queryKey: DatasetNavKeys.list(id) });
    }
  }, [skillStatus, queryClient, id]);

  if (navLoading && navList === null) {
    return <CompilationLoadingCard />;
  }

  if (!navLoading && (navList?.total ?? 0) === 0) {
    return (
      <CompilationEmptyState
        type="tree"
        disabled={(knowledgeBase?.chunk_count ?? 0) === 0}
        data={skillRunData}
      />
    );
  }

  return (
    <Card className="flex-1 min-h-0 overflow-hidden flex border-border-button rounded-xl flex-col">
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        <ResizablePanel defaultSize={33} minSize={20} maxSize={50}>
          <NavTreeLeftPanel
            navList={navList}
            navLoading={navLoading}
            childrenMap={childrenMap}
            deleteNavLoading={deleteNavLoading}
            deleteNodeLoading={deleteNodeLoading}
            onParentClick={handleParentClick}
            onChildClick={handleChildClick}
            onDeleteAll={handleDeleteAll}
            onDeleteNode={handleDeleteNode}
          />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel className="flex flex-col">
          {selectedNode ? (
            <section className="flex flex-col h-full">
              <header className="px-4 py-3 border-b border-border-button space-y-1">
                <h3 className="text-sm font-medium text-text-primary">
                  {selectedNode.displayName}
                </h3>
                <span className="text-xs text-text-secondary">
                  {t('datasetNav.docCount', { count: selectedNode.doc_count })}
                </span>
              </header>
              <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 text-sm text-text-primary whitespace-pre-wrap">
                {selectedNode.description || t('datasetNav.noDescription')}
              </div>
            </section>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-text-secondary">
              {t('datasetNav.selectNode')}
            </div>
          )}
        </ResizablePanel>
      </ResizablePanelGroup>
    </Card>
  );
}
