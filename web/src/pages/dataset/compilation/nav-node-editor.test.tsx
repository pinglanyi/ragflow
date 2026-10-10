import React from 'react';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import datasetNavService from '@/services/dataset-nav-service';
import { NavNodeEditor } from './nav-node-editor';

jest.mock('@/components/ui/button', () => ({
  Button: (props: any) => require('react').createElement('button', props),
}));
jest.mock('@/hooks/use-knowledge-request', () => ({
  useKnowledgeBaseId: () => 'kb-1',
}));
jest.mock('@/hooks/use-dataset-nav-request', () => ({
  DatasetNavKeys: { targets: (id: string) => ['dataset_nav', id, 'targets'] },
}));
jest.mock(
  'react-i18next',
  () => ({ useTranslation: () => ({ t: (key: string) => key }) }),
  { virtual: true },
);
jest.mock('@/services/dataset-nav-service', () => ({
  __esModule: true,
  default: { getNavTargets: jest.fn(), updateNavNode: jest.fn() },
}));

// The repository's Jest esbuild wrapper emits classic JSX outside Vite.
(globalThis as any).React = React;
afterEach(() => {
  cleanup();
  jest.clearAllMocks();
});

function mount(docId?: string) {
  jest.mocked(datasetNavService.getNavTargets).mockResolvedValue({
    data: {
      code: 0,
      data: { items: [{ name: 'topic-b', display_name: 'B' }] },
    },
  } as any);
  jest
    .mocked(datasetNavService.updateNavNode)
    .mockResolvedValue({ data: { code: 0 } } as any);
  const onSaved = jest.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <NavNodeEditor
        node={{
          name: 'node-a',
          displayName: 'A',
          description: 'note',
          parentName: 'projected-parent',
          docId,
        }}
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText('knowledgeCompilation.navEditMove'));
  return onSaved;
}

it('keeps the actual parent unchanged unless the user explicitly moves the node', async () => {
  const onSaved = mount('doc-1');
  await screen.findByText('B — topic-b');
  expect(screen.queryByText('knowledgeCompilation.navRoot')).toBeNull();
  fireEvent.change(
    screen.getByLabelText('knowledgeCompilation.navDisplayName'),
    { target: { value: '手册' } },
  );
  fireEvent.click(screen.getByText('knowledgeCompilation.navSave'));
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(datasetNavService.updateNavNode).toHaveBeenCalledWith(
    'kb-1',
    'node-a',
    { display_name: '手册', description: 'note' },
  );
});

it('submits an explicit target topic when moving a branch', async () => {
  mount();
  await screen.findByText('B — topic-b');
  expect(screen.getByText('knowledgeCompilation.navRoot')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('knowledgeCompilation.navMoveTo'), {
    target: { value: 'topic-b' },
  });
  fireEvent.click(screen.getByText('knowledgeCompilation.navSave'));
  await waitFor(() =>
    expect(datasetNavService.updateNavNode).toHaveBeenCalledWith(
      'kb-1',
      'node-a',
      {
        display_name: 'A',
        description: 'note',
        parent_name: 'topic-b',
      },
    ),
  );
});

it('shows server validation errors and leaves the form open', async () => {
  const onSaved = mount();
  await screen.findByText('B — topic-b');
  jest
    .mocked(datasetNavService.updateNavNode)
    .mockResolvedValue({
      data: { code: 102, message: 'Cannot move into descendant' },
    } as any);
  fireEvent.click(screen.getByText('knowledgeCompilation.navSave'));
  expect(await screen.findByRole('alert')).toHaveProperty(
    'textContent',
    'Cannot move into descendant',
  );
  expect(onSaved).not.toHaveBeenCalled();
});
