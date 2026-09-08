import { useFormContext, useWatch } from 'react-hook-form';
import { z } from 'zod';
import { useFetchAllAddedModels } from '@/hooks/use-llm-request';
import { RAGFlowFormItem } from './ragflow-form';
import { buildModelTree } from './model-tree-select';
import { TreeSelect } from './tree-select';
import { Input } from './ui/input';
import { Switch } from './ui/switch';
import { Textarea } from './ui/textarea';

export const multimodalParserSchema = z.object({
  enabled: z.boolean().optional(),
  model: z.string().optional(),
  prompt: z.string().optional(),
  max_tokens: z.coerce.number().int().min(256).max(65536).optional(),
  model_revision: z.string().optional(),
  enable_thinking: z.boolean().optional(),
  reuse: z.boolean().optional(),
}).refine((value) => !value.enabled || !!value.model, {
  message: '请选择多模态模型', path: ['model'],
}).optional();

export function MultimodalParserOptions({ ownerTenantId }: { ownerTenantId?: string }) {
  const form = useFormContext();
  const enabled = useWatch({ control: form.control, name: 'parser_config.multimodal.enabled' });
  const { data: models } = useFetchAllAddedModels(undefined, ownerTenantId);
  return (
    <div className="space-y-4 py-4">
      <RAGFlowFormItem name="parser_config.multimodal.enabled" label="Chunk 多模态解析">
        {(field) => <Switch checked={field.value ?? false} onCheckedChange={field.onChange} />}
      </RAGFlowFormItem>
      {enabled && <>
        <p className="text-sm text-text-secondary">将 Chunk 原图转换为可检索的 Markdown：文字转录、表格摊平、图片详细描述。请使用能生成截图的解析方式（推荐 DeepDOC），并关闭父子切分。支持 OpenAI 兼容的本地 vLLM 或商用 API。</p>
        <RAGFlowFormItem name="parser_config.multimodal.model" label="多模态模型">
          {(field) => <TreeSelect {...field} data={buildModelTree(models ?? [], ['vision'])} showSearch defaultExpandAll />}
        </RAGFlowFormItem>
        <RAGFlowFormItem name="parser_config.multimodal.prompt" label="解析提示词">
          {(field) => <Textarea {...field} value={field.value ?? ''} rows={7} placeholder="留空使用内置工业文档提示词：忠实 OCR、合并值逐行逐列补齐、嵌套表摊平、图片详细描述、直接输出 Markdown。" />}
        </RAGFlowFormItem>
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
    </div>
  );
}
