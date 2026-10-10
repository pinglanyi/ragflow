import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FormProvider, useForm } from 'react-hook-form';
import { Search1APIWidgets } from './index';
import { TooltipProvider } from '@/components/ui/tooltip';

jest.mock('@/components/form-container', () => ({
  FormContainer: ({ children }: any) => children,
}));
jest.mock('@/components/top-n-item', () => ({ TopNFormField: () => null }));
jest.mock('../../hooks/use-form-values', () => ({ useFormValues: () => ({}) }));
jest.mock('../../hooks/use-watch-form-change', () => ({
  useWatchFormChange: () => undefined,
}));
jest.mock('../components/form-wrapper', () => ({
  FormWrapper: ({ children }: any) => children,
}));
jest.mock('../components/output', () => ({ Output: () => null }));
jest.mock('../components/query-variable', () => ({
  QueryVariable: () => null,
}));
jest.mock('../../constant', () => ({
  Search1APIChannel: { General: 'general', News: 'news' },
  Search1APIServices: {
    general: ['google', 'github'],
    news: ['google', 'reuters'],
  },
  initialSearch1APISearchValues: { outputs: {} },
}));
jest.mock('@/components/originui/select-with-search', () => ({
  SelectWithSearch: ({ value, onChange, options, name }: any) => (
    <select
      aria-label={name}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option: any) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

function Harness({ service = 'github' }: { service?: string }) {
  const form = useForm({
    defaultValues: {
      channel: 'general',
      search_service: service,
      api_key: 'configured-key',
      top_n: 10,
    },
  });
  return (
    <TooltipProvider>
      <FormProvider {...form}>
        <Search1APIWidgets />
      </FormProvider>
    </TooltipProvider>
  );
}

test('switching to news replaces an unsupported service and preserves the key', async () => {
  render(<Harness />);
  expect(screen.getByLabelText('search_service')).toHaveValue('github');
  fireEvent.change(screen.getByLabelText('channel'), {
    target: { value: 'news' },
  });
  await waitFor(() =>
    expect(screen.getByLabelText('search_service')).toHaveValue('google'),
  );
  expect(screen.getByRole('option', { name: 'Reuters' })).toBeInTheDocument();
  expect(
    screen.queryByRole('option', { name: 'GitHub' }),
  ).not.toBeInTheDocument();
  expect(document.querySelector('input[type=password]')).toHaveValue(
    'configured-key',
  );
});

test('switching channels retains a valid selected service', async () => {
  render(<Harness service="google" />);
  fireEvent.change(screen.getByLabelText('channel'), {
    target: { value: 'news' },
  });
  await waitFor(() =>
    expect(screen.getByLabelText('search_service')).toHaveValue('google'),
  );
});
