"""Orchestration tests use an in-memory adapter, without model/DB dependencies."""
import asyncio
import ast
import importlib.util
import logging
import sys
from copy import deepcopy
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def engine():
    path = Path(__file__).parents[2] / 'rag/svr/task_executor_refactor/existing_chunks_compiler.py'
    spec = importlib.util.spec_from_file_location('existing_chunks_compiler', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retry_reuses_completed_documents_and_aggregates_once():
    module = engine()
    completed, calls, merges = set(), [], []
    failed = {'b'}

    async def compile_doc(doc):
        if doc in completed:
            return 'reused'
        calls.append(doc)
        if doc in failed:
            raise ValueError('model unavailable')
        completed.add(doc)
        return 'compiled'

    async def merge():
        merges.append(True)

    async def run():
        return await module.compile_documents(['a', 'b', 'c'], compile_doc, merge)

    with pytest.raises(RuntimeError, match='b.*model unavailable'):
        asyncio.run(run())
    assert completed == {'a', 'c'}
    assert merges == []
    failed.clear()
    result = asyncio.run(run())
    assert calls == ['a', 'b', 'c', 'b']
    assert result == {'compiled': 1, 'reused': 2, 'skipped': 0}
    assert merges == [True]


def test_cancellation_stops_before_aggregate():
    module = engine()
    calls = []

    async def compile_doc(doc):
        calls.append(doc)
        return 'compiled'

    async def merge():
        pytest.fail('cancelled operation must not aggregate')

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(module.compile_documents(['a', 'b'], compile_doc, merge, cancelled=lambda: bool(calls)))
    assert calls == ['a']


def test_fingerprint_changes_for_content_template_and_model_but_not_dict_order():
    fingerprint = engine().fingerprint
    args = ([{'id': '1', 'content_with_weight': 'hello'}], {'kind': 'timeline', 'rechunk': False}, 'chat', 'embed')
    initial = fingerprint(*args)
    assert initial == fingerprint(args[0], {'rechunk': False, 'kind': 'timeline'}, 'chat', 'embed')
    assert initial != fingerprint([{'id': '1', 'content_with_weight': 'edited'}], *args[1:])
    assert initial != fingerprint(args[0], {'kind': 'mind_map'}, *args[2:])
    assert initial != fingerprint(*args[:2], 'other', 'embed')


def production_adapter(monkeypatch):
    """Exercise the production adapter with an in-memory document store."""
    module = engine()
    original = [{'id': 'raw-a', 'doc_id': 'a', 'content_with_weight': '2025: Alpha released.', 'available_int': 1},
                {'id': 'raw-b', 'doc_id': 'b', 'content_with_weight': '2026: Beta released.', 'available_int': 1}]
    rows, cache, templates, calls, merges, progress = deepcopy(original), {}, {}, [], [], []
    fail = set()
    policy = ContextVar('test-strict', default=False)

    class Lock:
        def acquire(self, blocking): return True
        def owned(self): return True
        def release(self): pass
        def extend(self, *args): pass

    class Order:
        def asc(self, field): return self

    def matches(row, condition):
        for field, wanted in condition.items():
            if field == 'must_not':
                if wanted.get('exists') in row: return False
            elif field == 'exists':
                if wanted not in row: return False
            elif isinstance(wanted, list):
                actual = row.get(field)
                if isinstance(actual, list):
                    if not set(actual).intersection(wanted): return False
                elif actual not in wanted: return False
            elif row.get(field) != wanted: return False
        return True

    def search(fields, keywords, condition, match, order, offset, limit, index, kbs):
        return {r['id']: deepcopy(r) for r in [r for r in rows if matches(r, condition)][offset:offset + limit]}

    def delete(condition, *args):
        rows[:] = [r for r in rows if not matches(r, condition)]

    async def execute(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def compile_batches(**kwargs):
        assert policy.get()
        batches = [batch async for batch in kwargs['chunk_batches']]
        calls.append((kwargs['doc_id'], deepcopy(kwargs['active_templates']), batches))
        if kwargs['doc_id'] in fail: raise RuntimeError('provider failed')
        info = {}
        for tid, cfg in kwargs['active_templates']:
            rows.append({'id': kwargs['doc_id'] + tid, 'doc_id': kwargs['doc_id'],
                         'scope_kwd': 'doc', 'compile_kwd': cfg['kind'],
                         'compilation_template_ids': [tid], 'knowledge_graph_kwd': 'entity'})
            info[tid] = {'output_count': 1, 'compile_kwds': [cfg['kind']]}
        return info

    async def aggregate(*args, **kwargs):
        assert kwargs['incremental'] is False
        merges.append(args[4])
        return True

    async def refresh(*args): pass
    async def disabled(*args): return set()

    def doc(doc_id):
        document = {'id': doc_id, 'kb_id': 'kb', 'name': doc_id, 'status': '1', 'run': '3', 'parser_config': {}}
        return True, SimpleNamespace(**document, to_dict=lambda: deepcopy(document))

    attrs = {
        'api.apps.services.dataset_api_service': {'resolve_model_config': lambda *args: {}},
        'api.db.services.compilation_template_service': {'CompilationTemplateService': SimpleNamespace(
            get_saved=lambda tid, tenant: templates.get(tid), insert=lambda **cfg: templates.update({cfg['id']: cfg}),
            load_builtins_from_files=lambda: [{'kind': k, 'config': {'kind': k}} for k in module.TASK_KINDS['structure']])},
        'api.db.services.document_service': {'DocumentService': SimpleNamespace(get_by_id=doc)},
        'api.db.services.llm_service': {'LLMBundle': lambda *args, **kwargs: object()},
        'common': {'settings': SimpleNamespace(docStoreConn=SimpleNamespace(search=search, delete=delete, get_fields=lambda r, f: r))},
        'common.constants': {'LLMType': SimpleNamespace(CHAT='chat')},
        'common.doc_store.doc_store_base': {'OrderByExpr': Order},
        'common.exceptions': {'TaskCanceledException': type('TaskCanceledException', (Exception,), {})},
        'common.misc_utils': {'thread_pool_exec': execute},
        'rag.advanced_rag.knowlege_compile.runner': {'load_active_templates': lambda *args: [], 'run_structure_compile_over_batches': compile_batches},
        'rag.advanced_rag.knowlege_compile.structure': {'LLMCallPool': lambda *args, **kwargs: object(), '_struct_infer_type': lambda cfg: cfg['kind']},
        'rag.nlp': {'search': SimpleNamespace(index_name=lambda tenant: tenant)},
        'rag.svr.task_executor_refactor.chunk_post_processor': {'_parser_config_compilation_template_ids': lambda *args: []},
        'rag.svr.task_executor_refactor.compile_policy': {'strict_compilation': policy},
        'rag.svr.task_executor_refactor.dataset_structure_merger': {'_disabled_doc_ids': disabled, '_do_build': aggregate, '_refresh_index': refresh},
        'rag.utils.redis_conn': {'REDIS_CONN': SimpleNamespace(REDIS=SimpleNamespace(lock=lambda *args, **kwargs: Lock()),
            get=lambda key: cache.get(key), set=lambda k, v, ttl: cache.update({k: v}), delete=lambda k: cache.pop(k, None))},
    }
    for name, values in attrs.items():
        dependency = ModuleType(name)
        dependency.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, dependency)
    ctx = SimpleNamespace(task_type='structure', tenant_id='tenant', kb_id='kb', id='task',
        doc_ids=['a', 'b'], kb_parser_config={}, llm_id='chat', embd_id='embed', language='English',
        has_canceled_func=lambda task_id: False, progress_cb=lambda *args, **kwargs: progress.append((args, kwargs)))
    return SimpleNamespace(run=lambda: asyncio.run(module.run_existing_chunks_compile(ctx, object())),
        rows=rows, original=original, calls=calls, merges=merges, fail=fail, cache=cache, templates=templates)


def test_existing_chunks_adapter_preserves_sources_and_reuses_three_structures(monkeypatch):
    adapter = production_adapter(monkeypatch)
    adapter.run()
    assert [r for r in adapter.rows if 'compile_kwd' not in r] == adapter.original
    assert len(adapter.calls) == 2
    assert len(adapter.merges) == 3
    assert all(len(templates) == 3 for _, templates, _ in adapter.calls)
    assert all(cfg['rechunk'] is False and cfg['dataset_merge'] is False
               for _, templates, _ in adapter.calls for _, cfg in templates)
    adapter.run()
    assert len(adapter.calls) == 2  # No model calls for unchanged sources.
    adapter.rows[0]['content_with_weight'] = '2027: Alpha updated.'
    adapter.run()
    assert len(adapter.calls) == 3
    assert adapter.calls[-1][0] == 'a'
    assert adapter.rows[1] == adapter.original[1]


def test_existing_chunks_adapter_does_not_aggregate_or_cache_failed_document(monkeypatch):
    adapter = production_adapter(monkeypatch)
    adapter.fail.add('b')
    with pytest.raises(RuntimeError, match='provider failed'):
        adapter.run()
    assert not adapter.merges
    assert len(adapter.cache) == 3  # Successful document only, one checkpoint per kind.
    assert [r for r in adapter.rows if 'compile_kwd' not in r] == adapter.original
    adapter.fail.clear()
    adapter.run()
    assert [doc_id for doc_id, _, _ in adapter.calls] == ['a', 'b', 'b']
    assert len(adapter.merges) == 3


@pytest.mark.parametrize('compile_existing', [False, True])
def test_queue_opt_in_preserves_existing_requests_and_shares_three_trace_ids(compile_existing):
    path = Path(__file__).parents[2] / 'api/apps/services/dataset_api_service.py'
    function = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'run_index')
    calls, updates = [], []
    kb = SimpleNamespace(id='kb')
    scope = {'logging': logging,
        '_VALID_INDEX_TYPES': {'structure', 'graph'},
        '_INDEX_TYPE_TO_TASK_TYPE': {'structure': 'structure', 'graph': 'structure_graph'},
        '_INDEX_TYPE_TO_TASK_ID_FIELD': {'structure': 'structure_task_id', 'graph': 'graphrag_task_id'},
        '_INDEX_TYPE_TO_DISPLAY_NAME': {'structure': 'Structure', 'graph': 'Graph'},
        'GRAPH_RAPTOR_FAKE_DOC_ID': 'fake',
        'KnowledgebaseService': SimpleNamespace(accessible=lambda *args: True, get_by_id=lambda *args: (True, kb),
             update_by_id=lambda key, values: updates.append(values) or True),
        'DocumentService': SimpleNamespace(get_by_kb_id=lambda **kwargs: ([{'id': 'a', 'status': '1'}, {'id': 'disabled', 'status': '0'}], 2)),
        'TaskService': SimpleNamespace(get_by_id=lambda *args: (False, None)),
        'queue_raptor_o_graphrag_tasks': lambda **kwargs: calls.append(kwargs) or 'new-task'}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
    ok, result = scope['run_index']('kb', 'tenant', 'structure' if compile_existing else 'graph', compile_existing)
    assert ok and result == {'task_id': 'new-task'}
    assert calls[0]['doc_ids'] == ['a']
    assert calls[0].get('compile_existing_chunks', False) == compile_existing
    if compile_existing:
        assert all(updates[0][field] == 'new-task' for field in ['graphrag_task_id', 'mindmap_task_id', 'timeline_task_id'])
    else:
        assert updates == [{'graphrag_task_id': 'new-task'}]
    kb.timeline_task_id = 'running-task'
    scope['TaskService'].get_by_id = lambda *args: (True, SimpleNamespace(progress=0.5))
    if compile_existing:
        assert scope['run_index']('kb', 'tenant', 'structure', True)[0] is False
        assert len(calls) == 1


@pytest.mark.parametrize('operation', ['search', 'insert', 'delete', 'refresh'])
def test_strict_aggregation_surfaces_store_failures_without_changing_legacy_policy(monkeypatch, operation):
    production_adapter(monkeypatch)  # Install the lightweight doc-store types.
    policy = ContextVar('strict', default=False)
    path = Path(__file__).parents[2] / 'rag/svr/task_executor_refactor/dataset_structure_merger.py'
    function_name = {'search': '_index_search', 'insert': '_index_insert',
                     'delete': '_index_delete', 'refresh': '_refresh_index'}[operation]
    function = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == function_name)

    def fail(*args, **kwargs):
        raise RuntimeError('store unavailable')

    async def execute(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    store = SimpleNamespace(index_exist=lambda *args: True, search=fail, delete=fail,
                            insert=fail, refresh_idx=fail)
    scope = {'strict_compilation': policy, 'settings': SimpleNamespace(docStoreConn=store),
             '_index_name': lambda tenant: tenant, 'thread_pool_exec': execute,
             '_supports_bulk_refresh': lambda typ: False, 'logging': logging}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
    args = {'search': ('tenant', 'kb', {}, ['id']), 'insert': ('tenant', 'kb', [{'id': 'derived'}]),
            'delete': ('tenant', 'kb', {'compile_kwd': ['graph']}), 'refresh': ('tenant', 'kb')}[operation]
    asyncio.run(scope[function_name](*args))  # Legacy best-effort policy remains.
    policy.set(True)
    with pytest.raises(RuntimeError, match='store unavailable'):
        asyncio.run(scope[function_name](*args))
