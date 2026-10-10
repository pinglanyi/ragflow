import { fireEvent, render, screen } from '@testing-library/react';
import { FormProvider, useForm } from 'react-hook-form';
import { z } from 'zod';
import ChatBasicSetting from './chat-basic-settings';

jest.mock('@/hooks/common-hooks', () => ({
  useTranslate: () => ({ t: (key: string) => key }),
}));
jest.mock('@/components/avatar-name-description', () => ({ AvatarNameDescription: () => null }));
jest.mock('@/components/knowledge-base-item', () => ({ KnowledgeBaseFormField: () => null }));
jest.mock('@/components/llm-setting-items/next', () => ({ LlmSettingFieldItems: () => null }));
jest.mock('@/components/ui/form', () => ({
  FormField: () => null, FormControl: () => null, FormItem: () => null,
  FormLabel: () => null, FormMessage: () => null,
}));
jest.mock('@/components/llm-setting-items/failover-models-field', () => ({
  FailoverModelsField: ({ name }: { name: string }) => {
    const { field } = require('react-hook-form').useController({ name });
    return <button type="button" onClick={() => field.onChange(['backup-id'])}>Add backup</button>;
  },
}));

const schema = z.object({
  llm_setting: z.object({ failover_llm_ids: z.array(z.string()).optional() }),
});

it.each(['', 'chat.'])('submits backup IDs inside llm_setting with prefix %s', (prefix) => {
  const saved = jest.fn();
  function Harness() {
    const initial = { llm_id: 'primary', llm_setting: { failover_llm_ids: [] } };
    const form = useForm({ defaultValues: prefix ? { chat: initial } : initial });
    return <FormProvider {...form}>
      <form onSubmit={(event) => {
        event.preventDefault();
        const values = form.getValues() as any;
        saved(schema.parse(prefix ? values.chat : values));
      }}>
        <ChatBasicSetting prefix={prefix} hideName />
        <button type="submit">Save settings</button>
      </form>
    </FormProvider>;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: 'Add backup' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
  expect(saved).toHaveBeenCalledWith({ llm_setting: { failover_llm_ids: ['backup-id'] } });
});
