import { FileType } from '@/constants/file';
import { ModelTypeToField } from '@/constants/llm';
import { initialParserValues } from '../../constant/pipeline';
import {
  buildInitialParserSetup,
  buildInitialParserValues,
  resolvePdfParserProvider,
  supportsPdfPageRanges,
} from './utils';

describe('PDF parser page-range capabilities', () => {
  it('resolves opaque model IDs through the selected tenant model catalog', () => {
    const models = [
      { model_id: 'opaque-mineru-id', provider_name: 'MinerU' },
      { model_id: 'opaque-vision-id', provider_name: 'OpenAI' },
    ];
    expect(resolvePdfParserProvider('opaque-mineru-id', models)).toBe('MinerU');
    expect(
      supportsPdfPageRanges(
        'opaque-mineru-id',
        resolvePdfParserProvider('opaque-mineru-id', models),
      ),
    ).toBe(false);
    expect(
      supportsPdfPageRanges(
        'opaque-vision-id',
        resolvePdfParserProvider('opaque-vision-id', models),
      ),
    ).toBe(true);
    expect(supportsPdfPageRanges('model@instance@PaddleOCR')).toBe(false);
    expect(supportsPdfPageRanges('deepdoc')).toBe(true);
    expect(supportsPdfPageRanges('unresolved-model-id')).toBe(false);
  });
});

describe('parser-form utils', () => {
  describe('buildInitialParserSetup', () => {
    it('returns a deep copy of the default setup', () => {
      const setup = buildInitialParserSetup(FileType.PDF, {});
      expect(setup?.fileFormat).toBe(FileType.PDF);
      // Mutating the copy must not touch the shared defaults
      (setup as any).pages[0].from = 5;
      expect(buildInitialParserSetup(FileType.PDF, {})?.pages?.[0].from).toBe(
        1,
      );
    });

    it('prefills the tenant default model for video and audio', () => {
      const dictionary = {
        [ModelTypeToField.vision]: 'gpt-4o@OpenAI',
        [ModelTypeToField.asr]: 'whisper@OpenAI',
      };
      expect(buildInitialParserSetup(FileType.Video, dictionary)?.vlm).toEqual({
        llm_id: 'gpt-4o@OpenAI',
      });
      expect(buildInitialParserSetup(FileType.Audio, dictionary)?.vlm).toEqual({
        llm_id: 'whisper@OpenAI',
      });
    });

    it('leaves other file types untouched even with defaults present', () => {
      const dictionary = {
        [ModelTypeToField.vision]: 'gpt-4o@OpenAI',
        [ModelTypeToField.asr]: 'whisper@OpenAI',
      };
      expect(buildInitialParserSetup(FileType.PDF, dictionary)?.vlm).toBe(
        undefined,
      );
    });

    it('keeps the empty model id when no tenant default exists', () => {
      expect(buildInitialParserSetup(FileType.Audio, {})?.vlm).toEqual({
        llm_id: '',
      });
    });

    it('returns undefined for a file type without a default setup', () => {
      expect(buildInitialParserSetup('nope' as FileType, {})).toBeUndefined();
    });
  });

  describe('buildInitialParserValues', () => {
    it('prefills tenant default models across every default file type', () => {
      const values = buildInitialParserValues({
        [ModelTypeToField.vision]: 'gpt-4o@OpenAI',
        [ModelTypeToField.asr]: 'whisper@OpenAI',
      });

      const byFileType = new Map(
        values.setups.map((setup: any) => [setup.fileFormat, setup]),
      );
      expect(byFileType.get(FileType.Video)?.vlm).toEqual({
        llm_id: 'gpt-4o@OpenAI',
      });
      expect(byFileType.get(FileType.Audio)?.vlm).toEqual({
        llm_id: 'whisper@OpenAI',
      });
      expect(byFileType.get(FileType.PDF)?.vlm).toBe(undefined);
    });

    it('keeps every default file type and does not mutate the defaults', () => {
      const values = buildInitialParserValues({});
      expect(values.setups).toHaveLength(initialParserValues.setups.length);
      expect(initialParserValues.setups).toEqual(
        buildInitialParserValues({}).setups,
      );
    });
  });
});
