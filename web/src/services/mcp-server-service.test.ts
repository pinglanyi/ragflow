import request from '@/utils/request';
import service from './mcp-server-service';

jest.mock('@/utils/request', () => ({
  __esModule: true,
  default: { post: jest.fn() },
}));
jest.mock('@/utils/api', () => ({
  __esModule: true,
  default: { testMcpServer: (id: string) => `/mcp/${id}/test` },
}));

test('uses stored id for credential restoration even after a name edit', () => {
  service.test({
    mcp_id: 'stored-id',
    name: 'renamed',
    url: 'https://mcp.example',
    headers: { Authorization: '********' },
  });
  expect(request.post).toHaveBeenCalledWith('/mcp/stored-id/test', {
    data: {
      name: 'renamed',
      url: 'https://mcp.example',
      headers: { Authorization: '********' },
    },
  });
});

test('new connections retain preview behavior', () => {
  service.test({ name: 'new-server', url: 'https://mcp.example' });
  expect(request.post).toHaveBeenLastCalledWith('/mcp/new-server/test', {
    data: { name: 'new-server', url: 'https://mcp.example' },
  });
});
