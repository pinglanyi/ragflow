import { useFormContext, useWatch } from 'react-hook-form';
import { z } from 'zod';
import { useFetchAllAddedModels } from '@/hooks/use-llm-request';
import { RAGFlowFormItem } from './ragflow-form';
import { buildModelTree } from './model-tree-select';
import { TreeSelect } from './tree-select';
import { Input } from './ui/input';
import { Switch } from './ui/switch';
import { Textarea } from './ui/textarea';
import {
  DEFAULT_MULTIMODAL_PROMPT,
  DEFAULT_MULTIMODAL_ROUTER_PROMPT,
} from './multimodal-parser-defaults';

export const multimodalParserSchema = z.object({
  enabled: z.boolean().optional(),
  mode: z.enum(['off', 'smart', 'full']).optional(),
  model: z.string().optional(),
  prompt: z.string().optional(),
  max_tokens: z.coerce.number().int().min(256).max(65536).optional(),
  router_prompt: z.string().optional(),
  router_max_tokens: z.coerce.number().int().min(1).max(1024).optional(),
  model_revision: z.string().optional(),
  enable_thinking: z.boolean().optional(),
  reuse: z.boolean().optional(),
}).refine((value) => !value.enabled || !!value.model, {
  message: '请选择多模态模型', path: ['model'],
}).optional();

export function MultimodalParserOptions({ ownerTenantId, picture = false }: { ownerTenantId?: string; picture?: boolean }) {
  const form = useFormContext();
  const enabled = useWatch({ control: form.control, name: 'parser_config.multimodal.enabled' });
  const mode = useWatch({ control: form.control, name: 'parser_config.multimodal.mode' }) ?? (enabled ? 'full' : 'off');
  const { data: models } = useFetchAllAddedModels(undefined, ownerTenantId);
  return (
    <div className="space-y-4 py-4">
      <RAGFlowFormItem name="parser_config.multimodal.mode" label={picture ? '图片多模态策略' : 'Chunk 多模态策略'}>
        {(field) => <div className="grid grid-cols-3 gap-2">
          {([
            ['off', '不用多模态'],
            ['smart', '智能路由'],
            ['full', '全部多模态'],
          ] as const).map(([value, label]) => <button key={value} type="button" className={`rounded border px-3 py-2 text-sm ${mode === value ? 'border-accent-primary bg-accent-primary/10 text-accent-primary' : 'border-border-button'}`} onClick={() => { field.onChange(value); form.setValue('parser_config.multimodal.enabled', value !== 'off', { shouldDirty: true }); }}>{label}</button>)}
        </div>}
      </RAGFlowFormItem>
      {enabled && <>
        <p className="text-sm text-text-secondary">{picture
          ? '智能路由会先判断图片是否需要视觉恢复；全部多模态会直接生成文字转录、Markdown 表格和图片描述。'
          : '基础 Chunk 方法先负责分块。智能路由保留完整纯文本结果，只把表格、图片、复杂版式或 OCR 不足的 Chunk 交给视觉模型；全部多模态会处理每个 Chunk。PDF 直接渲染，Office 文件临时渲染，源文件位置与页码/幻灯片号保持不变。'}支持 OpenAI 兼容的本地 vLLM 或商用 API；模型类型请勾选视觉（vision）。</p>
        <RAGFlowFormItem name="parser_config.multimodal.model" label="多模态模型">
          {(field) => <TreeSelect {...field} data={buildModelTree(models ?? [], ['vision'])} showSearch defaultExpandAll />}
        </RAGFlowFormItem>
        <RAGFlowFormItem name="parser_config.multimodal.prompt" label="解析提示词">
          {(field) => <Textarea {...field} value={field.value ?? DEFAULT_MULTIMODAL_PROMPT} rows={12} placeholder="默认规则会忠实 OCR、摊平复杂表格并描述图片；可按知识库覆盖。" />}
        </RAGFlowFormItem>
        {mode === 'smart' && <>
          <RAGFlowFormItem name="parser_config.multimodal.router_prompt" label="智能路由提示词">
            {(field) => <Textarea {...field} value={field.value ?? DEFAULT_MULTIMODAL_ROUTER_PROMPT} rows={7} placeholder="默认规则：纯文本保留 OCR；其余内容进入多模态解析。" />}
          </RAGFlowFormItem>
          <RAGFlowFormItem name="parser_config.multimodal.router_max_tokens" label="路由最大输出 Token">
            {(field) => <Input {...field} value={field.value ?? 64} type="number" min={1} max={1024} />}
          </RAGFlowFormItem>
        </>}
        <RAGFlowFormItem name="parser_config.multimodal.max_tokens" label="最大输出 Token">
          {(field) => <Input {...field} value={field.value ?? 8192} type="number" min={256} max={65536} />}
        </RAGFlowFormItem>
        <RAGFlowFormItem name="parser_config.multimodal.enable_thinking" label="Qwen 思考模式">
          {(field) => <Switch checked={field.value ?? false} onCheckedChange={field.onChange} />}
        </RAGFlowFormItem>
        <RAGFlowFormItem name="parser_config.multimodal.model_revision" label="模型版本标记">
          {(field) => <Input {...field} value={field.value ?? ''} placeholder="本地权重升级后修改，例如 v2，避免复用旧结果" />}
        </RAGFlowFormItem>
        <RAGFlowFormItem name="parser_config.multimodal.reuse" label="复用已归档解析结果">
          {(field) => <Switch checked={field.value ?? true} onCheckedChange={field.onChange} />}
        </RAGFlowFormItem>
        <p className="text-sm text-text-secondary">原图、原始响应与 Markdown 均独立归档。复用按截图内容与模型配置匹配，不依赖 Chunk 数量或顺序。关闭复用会新增解析版本，旧记录仍保留。</p>
      </>}
      {picture && !enabled && <p className="text-sm text-text-secondary">当前使用默认 OCR / 短文本图片描述流程。开启后可直接理解接线图、流程图和复杂表格；已解析图片需要重新解析才会应用新设置。</p>}
    </div>
  );
}
