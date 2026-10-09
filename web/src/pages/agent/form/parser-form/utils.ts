import { FileType } from '@/constants/file';
import { cloneDeep } from 'lodash';
import { pickByBackend } from '@/utils/backend-variant';
import {
  FileTypeDefaultModelFieldMap,
  initialParserValues,
} from '../../constant/pipeline';

export function buildFieldNameWithPrefix(name: string, prefix: string) {
  return `${prefix}.${name}`;
}

const externalPdfParsers = [
  'mineru',
  'paddleocr',
  'docling',
  'opendataloader',
  'tcadp parser',
  'somark',
  'mistral ocr',
];

export function resolvePdfParserProvider(
  method: string | undefined,
  models: { model_id: string; provider_name: string }[],
) {
  return (
    models.find((model) => model.model_id === method)?.provider_name ||
    (method?.includes('@') ? method.split('@').at(-1) : undefined)
  );
}

function pdfParserResolved(method?: string, provider?: string) {
  const value = (method ?? '').toLowerCase();
  return (
    !value ||
    ['deepdoc', 'plain_text', 'plain text', ...externalPdfParsers].includes(
      value,
    ) ||
    Boolean(provider || method?.includes('@'))
  );
}

export function supportsPdfPageRanges(method?: string, provider?: string) {
  const value = (method ?? '').toLowerCase();
  const selectedProvider = (
    provider ||
    resolvePdfParserProvider(method, []) ||
    ''
  ).toLowerCase();
  return pickByBackend({
    go: true,
    python:
      pdfParserResolved(method, provider) &&
      !externalPdfParsers.some(
        (name) => value === name || selectedProvider === name,
      ),
  });
}

export function pdfPageRangeParams(
  method: string | undefined,
  pages: { from: number; to: number }[] | undefined,
  provider?: string,
) {
  const unresolved = pickByBackend({
    go: false,
    python: !pdfParserResolved(method, provider),
  });
  if (unresolved && pages?.length) {
    throw new Error(
      'PDF parser model is unresolved; wait for the model list before saving page ranges.',
    );
  }
  return supportsPdfPageRanges(method, provider)
    ? { pages: pages?.map((page) => [page.from, page.to]) ?? [] }
    : {};
}

// Builds the default setup for a file type being added to the parser form,
// prefilling the tenant default model for types that have one (video/audio).
export function buildInitialParserSetup(
  fileType: FileType,
  defaultModelDictionary: Record<string, string>,
) {
  const setup = initialParserValues.setups.find(
    (x) => x.fileFormat === fileType,
  );
  if (!setup) {
    return undefined;
  }

  const nextSetup = cloneDeep(setup) as Record<string, any>;
  const field = FileTypeDefaultModelFieldMap[fileType];
  const modelId = field ? defaultModelDictionary[field] : '';
  if (modelId) {
    nextSetup.vlm = { ...nextSetup.vlm, llm_id: modelId };
  }
  return nextSetup;
}

// Form values for a freshly added Parser node: every default file type with its
// tenant default model prefilled. Only applies to node creation — an existing
// form is shown as saved, so a cleared model stays cleared.
export function buildInitialParserValues(
  defaultModelDictionary: Record<string, string>,
) {
  return {
    ...initialParserValues,
    setups: initialParserValues.setups.map(
      (setup) =>
        buildInitialParserSetup(
          setup.fileFormat as FileType,
          defaultModelDictionary,
        ) ?? setup,
    ),
  };
}
