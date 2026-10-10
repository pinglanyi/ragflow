"""Compile source chunks without invoking ingestion, then aggregate once.

Imports of production services are deliberately local so orchestration can be
tested independently of databases and model runtimes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from copy import deepcopy


def fingerprint(chunks, config, chat_id, embedding_id):
    digest = hashlib.sha256()
    for value in (config, chat_id, embedding_id):
        digest.update(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode())
    for row in chunks:
        digest.update(json.dumps([row['id'], row.get('content_with_weight', '')], ensure_ascii=False).encode())
    return digest.hexdigest()


async def compile_documents(documents, compile_document, aggregate, *, cancelled=lambda: False, progress=lambda *args: None):
    counts = {'compiled': 0, 'reused': 0, 'skipped': 0}
    errors = []
    for number, document in enumerate(documents):
        if cancelled():
            raise asyncio.CancelledError()
        progress(number, len(documents), document)
        try:
            state = await compile_document(document)
            counts[state] += 1
        except Exception as error:
            logging.exception('Existing-chunk compilation failed for document %s', document)
            errors.append(f'{document}: {error}')
    if cancelled():
        raise asyncio.CancelledError()
    if errors:
        raise RuntimeError(f'{len(errors)} document(s) failed; aggregation withheld. ' + '; '.join(errors[:10]))
    await aggregate()
    return counts


TASK_KINDS = {
    'structure_graph': ('knowledge_graph',),
    'structure_mindmap': ('mind_map',),
    'timeline': ('timeline',),
    'structure': ('knowledge_graph', 'mind_map', 'timeline'),
}


async def run_existing_chunks_compile(ctx, embedding_model):
    from api.apps.services.dataset_api_service import resolve_model_config
    from api.db.services.compilation_template_service import CompilationTemplateService
    from api.db.services.document_service import DocumentService
    from api.db.services.llm_service import LLMBundle
    from common import settings
    from common.constants import LLMType
    from common.doc_store.doc_store_base import OrderByExpr
    from common.exceptions import TaskCanceledException
    from common.misc_utils import thread_pool_exec
    from rag.advanced_rag.knowlege_compile.runner import load_active_templates, run_structure_compile_over_batches
    from rag.advanced_rag.knowlege_compile.structure import LLMCallPool, _struct_infer_type
    from rag.nlp import search
    from rag.svr.task_executor_refactor.chunk_post_processor import _parser_config_compilation_template_ids
    from rag.svr.task_executor_refactor.compile_policy import strict_compilation
    from rag.svr.task_executor_refactor.dataset_structure_merger import _disabled_doc_ids, _do_build, _refresh_index
    from rag.utils.redis_conn import REDIS_CONN

    kinds = TASK_KINDS[ctx.task_type]
    index = search.index_name(ctx.tenant_id)
    # Same KB lock across the individual and combined entry points. The lease
    # is renewed while working; lost ownership prevents any further writes.
    lock = REDIS_CONN.REDIS.lock(f'existing-compile:{ctx.tenant_id}:{ctx.kb_id}', timeout=120, thread_local=False)
    if not await thread_pool_exec(lock.acquire, False):
        raise RuntimeError('Existing-chunk compilation is already running for this dataset.')
    lease_lost = asyncio.Event()

    async def renew():
        while True:
            await asyncio.sleep(30)
            try:
                await thread_pool_exec(lock.extend, 120, True)
            except Exception:
                lease_lost.set()
                return

    lease = asyncio.create_task(renew())
    pairs = set()
    models = {}
    errors = []
    pool = LLMCallPool(3, on_error=lambda label, context, error_type: errors.append(f'{label}: {error_type}'))

    def check():
        if lease_lost.is_set():
            raise RuntimeError('Compilation lock lost; retry this operation.')
        if ctx.has_canceled_func(ctx.id):
            raise TaskCanceledException('Existing-chunk compilation cancelled')

    async def load_chunks(doc_id):
        fields = ['id', 'content_with_weight', 'chunk_order_int', 'page_num_int', 'top_int']
        order = OrderByExpr().asc('chunk_order_int').asc('page_num_int').asc('top_int').asc('id')
        chunks = []
        seen = set()
        expected = None
        offset = 0
        while True:
            check()
            result = await thread_pool_exec(settings.docStoreConn.search, fields, [],
                {'doc_id': [doc_id], 'available_int': 1, 'must_not': {'exists': 'compile_kwd'}},
                [], order, offset, 500, index, [ctx.kb_id])
            rows = settings.docStoreConn.get_fields(result, fields) or {}
            get_total = getattr(settings.docStoreConn, 'get_total', None)
            if expected is None and callable(get_total):
                expected = get_total(result)
            if seen.intersection(rows):
                raise RuntimeError(f'{doc_id}: source pagination repeated chunks; retry after parsing completes')
            seen.update(rows)
            chunks.extend(dict(row, id=row_id) for row_id, row in rows.items()
                          if str(row.get('content_with_weight') or '').strip())
            if len(rows) < 500:
                if expected is not None and len(seen) != expected:
                    raise RuntimeError(f'{doc_id}: incomplete source read ({len(seen)}/{expected}); no checkpoint saved')
                return chunks
            offset += 500

    async def output_exists(doc_id, tid):
        result = await thread_pool_exec(settings.docStoreConn.search, ['id'], [],
            {'doc_id': [doc_id], 'scope_kwd': ['doc'], 'compilation_template_ids': [tid],
             'knowledge_graph_kwd': ['entity', 'relation']}, [], OrderByExpr(), 0, 1, index, [ctx.kb_id])
        return bool(settings.docStoreConn.get_fields(result, ['id']))

    def templates_for(document):
        config = {**ctx.kb_parser_config, **(document.get('parser_config') or {})}
        configured = load_active_templates(_parser_config_compilation_template_ids(config, ctx.tenant_id), ctx.tenant_id)
        selected = [(tid, cfg) for tid, cfg in configured if cfg.get('kind') in kinds]
        for kind in kinds:
            if any(cfg.get('kind') == kind for _, cfg in selected):
                continue
            # Stable tenant-specific identity makes the default editable in
            # the normal template editor, and avoids duplicate copies on retry.
            tid = hashlib.sha256(f'existing-chunks:v1:{ctx.tenant_id}:{kind}'.encode()).hexdigest()[:32]
            saved = CompilationTemplateService.get_saved(tid, ctx.tenant_id)
            if not saved:
                builtin = next(item for item in CompilationTemplateService.load_builtins_from_files() if item['kind'] == kind)
                CompilationTemplateService.insert(id=tid, tenant_id=ctx.tenant_id, kind=kind,
                    name=f"Existing chunks - {kind}", description='Default for existing-chunk compilation',
                    config=builtin['config'], is_builtin=False, status='1')
                saved = CompilationTemplateService.get_saved(tid, ctx.tenant_id)
            selected.append((tid, saved['config']))
        # Rechunking and synthesis are deliberately disabled only for this
        # operation. The saved custom template remains untouched.
        return [(tid, {**deepcopy(cfg), 'dataset_merge': False, 'rechunk': False,
                       'synthesis': {'enabled': False}}) for tid, cfg in selected], config

    async def compile_document(doc_id):
        check()
        found, doc = DocumentService.get_by_id(doc_id)
        if not found or doc.kb_id != ctx.kb_id:
            raise RuntimeError(f'Document {doc_id} no longer belongs to this dataset')
        if str(doc.status) == '0':
            return 'skipped'
        document = doc.to_dict()
        if str(document.get('run')) in ('1', '5'):
            raise RuntimeError(f"{doc.name}: source parsing is still running; retry after it completes")
        active, config = templates_for(document)
        chunks = await load_chunks(doc_id)
        if not chunks:
            ctx.progress_cb(msg=f'{doc.name}: skipped (no available nonblank source chunks)')
            return 'skipped'
        chat_id = config.get('llm_id') or ctx.llm_id
        if chat_id not in models:
            model_config = resolve_model_config(ctx.tenant_id, LLMType.CHAT, chat_id)
            models[chat_id] = LLMBundle(ctx.tenant_id, model_config, lang=ctx.language)
        pending = []
        checkpoints = {}
        for tid, cfg in active:
            key = f'existing-compile:v1:{ctx.tenant_id}:{ctx.kb_id}:{doc_id}:{tid}'
            digest = fingerprint(chunks, cfg, getattr(models[chat_id], 'model_config', chat_id),
                                 getattr(embedding_model, 'model_config', ctx.embd_id))
            cached = await thread_pool_exec(REDIS_CONN.get, key)
            if cached:
                cached = json.loads(cached)
            pairs.add((_struct_infer_type(cfg), tid, cfg['kind']))
            if cached and cached.get('digest') == digest and (cached.get('empty') or await output_exists(doc_id, tid)):
                pairs.update((kwd, tid, cfg['kind']) for kwd in cached.get('compile_kwds', []))
                continue
            pending.append((tid, cfg))
            checkpoints[tid] = (key, digest)
        if not pending:
            return 'reused'
        # Delete ONLY this document's derived rows for the selected templates.
        # Old dataset aggregates remain visible until preparation completes.
        for tid, _ in pending:
            check()
            await thread_pool_exec(REDIS_CONN.delete, checkpoints[tid][0])
            await thread_pool_exec(settings.docStoreConn.delete,
                {'doc_id': [doc_id], 'scope_kwd': ['doc'], 'compilation_template_ids': [tid],
                 'exists': 'compile_kwd'}, index, ctx.kb_id)
        async def batches():
            for start in range(0, len(chunks), 128):
                check()
                yield chunks[start:start + 128]
        errors.clear()
        def progress(*args, **kwargs):
            check()
            message = kwargs.get('msg') or (args[1] if len(args) > 1 else '')
            ctx.progress_cb(msg=f'{doc.name}: {message}')
        info = await run_structure_compile_over_batches(active_templates=pending,
            chat_mdl_by_tid={tid: models[chat_id] for tid, _ in pending}, embedding_model=embedding_model,
            tenant_id=ctx.tenant_id, kb_id=ctx.kb_id, doc_id=doc_id, doc_name=doc.name,
            language=ctx.language, chunk_batches=batches(), progress_cb=progress,
            cancel_check=lambda: ctx.has_canceled_func(ctx.id) or lease_lost.is_set(), llm_pool=pool)
        check()
        if errors:
            raise RuntimeError('; '.join(errors[:3]))
        # A concurrent edit must never be checkpointed as the old source.
        current = await load_chunks(doc_id)
        for tid, cfg in pending:
            key, digest = checkpoints[tid]
            if fingerprint(current, cfg, getattr(models[chat_id], 'model_config', chat_id),
                           getattr(embedding_model, 'model_config', ctx.embd_id)) != digest:
                raise RuntimeError(f'{doc.name}: source changed during compilation; retry')
        await _refresh_index(ctx.tenant_id, ctx.kb_id)
        for tid, cfg in pending:
            key, digest = checkpoints[tid]
            kwds = info[tid].get('compile_kwds', [])
            exists = await output_exists(doc_id, tid)
            if info[tid].get('output_count', 0) and not exists and cfg['kind'] != 'timeline':
                raise RuntimeError(f'{doc.name}: compiled output was not persisted for {tid}')
            if not exists:
                ctx.progress_cb(msg=f"{doc.name}: no matching {cfg['kind']} items extracted; empty result recorded")
            pairs.update((kwd, tid, cfg['kind']) for kwd in kwds)
            await thread_pool_exec(REDIS_CONN.set, key, json.dumps({'digest': digest, 'empty': not exists,
                'compile_kwds': kwds}), 30 * 24 * 3600)
        return 'compiled'

    async def aggregate():
        check()
        if not pairs:
            raise RuntimeError('No structures were extracted. Check the source content and template rules.')
        disabled = await _disabled_doc_ids(ctx.kb_id)
        for number, (kwd, tid, kind) in enumerate(sorted(pairs)):
            check()
            ctx.progress_cb(prog=0.85 + 0.14 * number / len(pairs), msg=f'Aggregating {kind} ...')
            if not await _do_build(ctx.tenant_id, ctx.kb_id, kwd, tid, kind, embedding_model,
                                   incremental=False, disabled_doc_ids=disabled):
                raise RuntimeError(f'Aggregation failed for {kind}; retry')
        await _refresh_index(ctx.tenant_id, ctx.kb_id)

    token = strict_compilation.set(True)
    try:
        counts = await compile_documents(ctx.doc_ids, compile_document, aggregate,
            cancelled=lambda: ctx.has_canceled_func(ctx.id),
            progress=lambda number, total, doc: ctx.progress_cb(prog=0.02 + 0.8 * number / max(total, 1),
                msg=f'Preparing document {number + 1}/{total}: {doc}'))
        ctx.progress_cb(prog=1, msg=f"Done: {counts['compiled']} compiled, {counts['reused']} reused, {counts['skipped']} skipped; structures aggregated.")
    except asyncio.CancelledError:
        raise TaskCanceledException('Existing-chunk compilation cancelled')
    finally:
        strict_compilation.reset(token)
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)
        if await thread_pool_exec(lock.owned):
            await thread_pool_exec(lock.release)
