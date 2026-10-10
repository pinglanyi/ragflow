import { ParseType } from '@/constants/knowledge';
import { formSchema } from '../form-schema';

// Validate the real schema without booting the browser router in jsdom.
jest.mock('@/routes', () => ({ Routes: {} }));

describe('dataset compilation template settings', () => {
  it.each(['wiki-template', ['wiki-template', 'tree-template']])(
    'preserves selected template groups when saving: %p',
    (groupIds) => {
      const result = formSchema.parse({
        name: 'Regression dataset',
        parse_type: ParseType.BuiltIn,
        chunk_method: 'naive',
        embedding_model: 'embedding-id',
        pagerank: 0,
        parser_config: {
          layout_recognize: 'DeepDOC',
          chunk_token_num: 512,
          delimiter: '\n',
          enable_children: false,
          children_delimiter: '\n',
          html4excel: false,
          compilation_template_group_id: groupIds,
        },
      });
      expect(result.parser_config?.compilation_template_group_id).toEqual(groupIds);
    },
  );
});
