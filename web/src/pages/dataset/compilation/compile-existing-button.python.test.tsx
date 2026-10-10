import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { compileExistingChunks } from '@/services/knowledge-service';
import { useTraceRunData } from '@/hooks/use-dataset-generate';
import message from '@/components/ui/message';
import { CompileExistingButton } from './compile-existing-button.python';

jest.mock('react-router', () => ({ useParams: () => ({ id: 'kb1' }) }));
jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
jest.mock('@/services/knowledge-service', () => ({
  compileExistingChunks: jest.fn(),
}));
jest.mock('@/hooks/use-dataset-generate', () => ({
  useTraceRunData: jest.fn(() => ({ data: {} })),
  DatasetGenerateKeys: { traceById: (type: string, id: string) => [type, id] },
}));
jest.mock('@/components/ui/message', () => ({
  __esModule: true,
  default: { success: jest.fn(), error: jest.fn() },
}));

function mount() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  const invalidate = jest.spyOn(client, 'invalidateQueries');
  render(
    React.createElement(
      QueryClientProvider,
      { client },
      React.createElement(CompileExistingButton, { enabled: true }),
    ),
  );
  return invalidate;
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(useTraceRunData).mockReturnValue({ data: {} } as never);
});

it('starts one operation and refreshes all three progress views', async () => {
  jest
    .mocked(compileExistingChunks)
    .mockResolvedValue({ data: { code: 0 } } as never);
  const invalidate = mount();
  fireEvent.click(screen.getByRole('button'));
  await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(3));
  expect(compileExistingChunks).toHaveBeenCalledWith('kb1');
});

it('blocks duplicate clicks while a dataset task is running', () => {
  jest
    .mocked(useTraceRunData)
    .mockReturnValue({ data: { progress: 0.5 } } as never);
  mount();
  expect(screen.getByRole('button')).toBeDisabled();
  fireEvent.click(screen.getByRole('button'));
  expect(compileExistingChunks).not.toHaveBeenCalled();
});

it('surfaces business errors without reporting success', async () => {
  jest
    .mocked(compileExistingChunks)
    .mockResolvedValue({
      data: { code: 1, message: 'already running' },
    } as never);
  const invalidate = mount();
  fireEvent.click(screen.getByRole('button'));
  await waitFor(() =>
    expect(message.error).toHaveBeenCalledWith('already running'),
  );
  expect(message.success).not.toHaveBeenCalled();
  expect(invalidate).not.toHaveBeenCalled();
});
