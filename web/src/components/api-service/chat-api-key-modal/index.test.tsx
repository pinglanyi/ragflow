import { render, screen } from '@testing-library/react';
import ChatApiKeyModal from './index';

let mockTokens: any[] = [];
jest.mock('../hooks', () => ({
  useOperateApiKey: () => ({
    tokenList: mockTokens,
    createToken: jest.fn(),
    removeToken: jest.fn(),
  }),
}));
jest.mock('@/hooks/common-hooks', () => ({
  useTranslate: () => ({ t: (key: string) => key }),
}));
jest.mock('@/components/copy-to-clipboard', () => () => null);
jest.mock('@/components/ui/dialog', () => {
  const React = require('react');
  const Box = ({ children }: any) => React.createElement('div', null, children);
  return {
    Dialog: Box,
    DialogContent: Box,
    DialogHeader: Box,
    DialogTitle: Box,
  };
});

describe('API key creation limit', () => {
  it.each([0, 1, 15])('allows another key with %i existing keys', (count) => {
    mockTokens = Array.from({ length: count }, (_, i) => ({
      token: String(i),
    }));
    render(<ChatApiKeyModal idKey="dialog_id" hideModal={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'createNewKey' })).toBeEnabled();
  });

  it('disables creation at 16 keys', () => {
    mockTokens = Array.from({ length: 16 }, (_, i) => ({ token: String(i) }));
    render(<ChatApiKeyModal idKey="dialog_id" hideModal={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'createNewKey' })).toBeDisabled();
  });
});
