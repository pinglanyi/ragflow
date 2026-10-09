import { FileType } from '@/constants/file';
import { ParserFields } from '../../constant/pipeline';
import { FormSchema } from './schema';

describe('parser FormSchema', () => {
  it('persists explicit global vision settings and retains inherited defaults', () => {
    const base = {
      setups: [{ fileFormat: FileType.PDF, parse_method: 'plain_text' }],
    };
    expect(
      (FormSchema.parse(base) as any).enable_vision_enhancement,
    ).toBeUndefined();
    const enabled = FormSchema.parse({
      ...base,
      enable_vision_enhancement: true,
      vlm: { llm_id: 'vision@provider' },
    }) as any;
    expect(enabled.enable_vision_enhancement).toBe(true);
    expect(enabled.vlm.llm_id).toBe('vision@provider');
    expect(
      (FormSchema.parse({ ...base, enable_vision_enhancement: false }) as any)
        .enable_vision_enhancement,
    ).toBe(false);
  });
  it('accepts video and audio setups without a model', () => {
    const result = FormSchema.safeParse({
      setups: [
        { fileFormat: FileType.Video, output_format: 'text' },
        { fileFormat: FileType.Audio, output_format: 'text' },
      ],
    });
    expect(result.success).toBe(true);
  });

  it('requires at least one file type', () => {
    const result = FormSchema.safeParse({ setups: [] });
    expect(result.success).toBe(false);
  });

  it('still requires fields for email', () => {
    const result = FormSchema.safeParse({
      setups: [{ fileFormat: FileType.Email, output_format: 'text' }],
    });
    expect(result.success).toBe(false);

    const withFields = FormSchema.safeParse({
      setups: [
        {
          fileFormat: FileType.Email,
          output_format: 'text',
          fields: Object.values(ParserFields),
        },
      ],
    });
    expect(withFields.success).toBe(true);
  });
});
