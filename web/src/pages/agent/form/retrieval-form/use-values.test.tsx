import { renderHook } from '@testing-library/react';
import { useValues } from './use-values';

describe('legacy retrieval source compatibility', () => {
  it('keeps memory-only old DSLs on the memory source', () => {
    const node: any = { data: { form: { memory_ids: ['memory-1'] } } };
    const { result } = renderHook(() => useValues(node));
    expect(result.current.retrieval_from).toBe('memory');
    expect(result.current.memory_ids).toEqual(['memory-1']);
  });

  it('preserves legacy dataset IDs', () => {
    const node: any = { data: { form: { kb_ids: ['kb-1'] } } };
    const { result } = renderHook(() => useValues(node));
    expect(result.current.retrieval_from).toBe('dataset');
    expect(result.current.dataset_ids).toEqual(['kb-1']);
  });

  it('respects an explicitly selected source', () => {
    const node: any = { data: { form: { retrieval_from: 'dataset', memory_ids: ['memory-1'] } } };
    const { result } = renderHook(() => useValues(node));
    expect(result.current.retrieval_from).toBe('dataset');
  });
});
