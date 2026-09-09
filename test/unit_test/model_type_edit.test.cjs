// Isolated hook regression: node --test test/unit_test/model_type_edit.test.cjs
// Set TYPESCRIPT_PATH if TypeScript is not installed in web/node_modules.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const ts = require(process.env.TYPESCRIPT_PATH || path.join(root, 'web/node_modules/typescript'));
const base = 'web/src/pages/user-setting/setting-model/instance-card/';
const original = { name: 'qwen3-emb-0_6b', model_types: ['chat'], max_tokens: 0 };
const edited = { ...original, model_types: ['embedding'] };
function harness(patchResult = { code: 0 }) {
  let state = [], cursor = 0;
  const calls = [];
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in state)) state[i] = initial;
      return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }];
    },
    useMemo: fn => fn(), useCallback: fn => fn,
    useEffect: () => {}, useRef: value => ({ current: value }),
  };
  const modules = {
    react,
    '@/constants/llm': { LLMFactory: {} },
    '@/hooks/common-hooks': { useTranslate: () => ({ t: x => x }) },
    '@/hooks/use-llm-request': { usePatchInstanceModel: () => ({
      patchInstanceModel: async value => { calls.push(value); return patchResult; }, loading: false,
    }) },
    '../available-models': { sortModelTypes: x => x },
  };
  function load(file) {
    const output = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    }).outputText;
    const exports = {};
    vm.runInNewContext(output, { exports, require: id => {
      if (!(id in modules)) throw new Error(`Unexpected dependency ${id}`);
      return modules[id];
    }, console });
    return exports;
  }
  const fields = load(base + 'use-custom-model-fields.tsx');
  modules['../use-custom-model-fields'] = fields;
  const hooks = load(base + 'models-section/hooks.ts');
  return { hooks, fields, calls, render: args => { cursor = 0; return hooks.useModelEdit(args); } };
}
test('model types are required checkboxes using backend canonical values', () => {
  const field = harness().fields.MODEL_FIELD_SCHEMA.find(f => f.name === 'model_types');
  assert.equal(field.type, 'checkbox-group');
  assert.equal(field.required, true);
  assert.ok(field.options.some(x => x.value === 'vision'));
  assert.ok(field.options.some(x => x.value === 'asr'));
});
test('draft edit updates save payload without calling persisted-model API', async () => {
  const h = harness();
  let draft = [original], catalog = [original];
  const args = { providerName: 'VLLM', instanceName: '__draft__', isDraftInstance: true,
    addedSet: new Set([original.name]), setDraftModels: fn => { draft = fn(draft); },
    setCatalog: fn => { catalog = fn(catalog); } };
  h.render(args).setEditingModel(original);
  await h.render(args).handleEditSubmit(edited);
  assert.equal(h.calls.length, 0);
  assert.equal(h.hooks.buildModelInfo(draft)[0].model_type[0], 'embedding');
  assert.equal(catalog[0].model_types[0], 'embedding');
});
test('saved explicit types win over inferred catalog on refresh', () => {
  const h = harness();
  const result = h.hooks.useModelsDerived({ catalog: [original], instanceModels: [edited], draftModels: [], isDraftInstance: false });
  assert.equal(result.models[0].model_types[0], 'embedding');
});
test('unadded catalog model can be edited before adding it', async () => {
  const h = harness(); let catalog = [original];
  const args = { providerName: 'VLLM', instanceName: 'local', isDraftInstance: false,
    addedSet: new Set(), setDraftModels: () => {}, setCatalog: fn => { catalog = fn(catalog); } };
  h.render(args).setEditingModel(original);
  await h.render(args).handleEditSubmit(edited);
  assert.equal(h.calls.length, 0);
  assert.equal(catalog[0].model_types[0], 'embedding');
});
test('failed saved edit retains dialog and does not publish unpersisted values', async () => {
  const h = harness({ code: 100, message: 'rejected' }); let catalog = [original];
  const args = { providerName: 'VLLM', instanceName: 'local', isDraftInstance: false,
    addedSet: new Set([original.name]), setDraftModels: () => {}, setCatalog: fn => { catalog = fn(catalog); } };
  h.render(args).setEditingModel(original);
  await h.render(args).handleEditSubmit(edited);
  assert.equal(h.calls[0].model_type[0], 'embedding');
  assert.equal(catalog[0].model_types[0], 'chat');
  assert.ok(h.render(args).editingModel);
});
test('provider verify button uses the latest manually selected model types', async () => {
  const file = path.join(root, base, 'hooks.tsx');
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const fn = source.statements.find(n => ts.isFunctionDeclaration(n) && n.name.text === 'useVerifyProvider');
  const code = ts.transpileModule(fn.getText(source), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {}, calls = [];
  vm.runInNewContext(code, { exports, useCallback: fn => fn,
    useVerifyProviderConnection: () => ({ verifyProviderConnection: async value => { calls.push(value); return { code: 0 }; } }) });
  const selected = { current: [{ model_name: original.name, model_type: ['chat'] }] };
  const verify = exports.useVerifyProvider('VLLM', { current: { getValues: () => ({ api_key: 'test' }) } }, undefined, selected);
  selected.current = [{ model_name: original.name, model_type: ['embedding'] }];
  await verify({});
  assert.equal(calls[0].model_info?.[0].model_type[0], 'embedding');
});
