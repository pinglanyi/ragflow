import {
  ModelTreeSelectFormField,
  ModelTypeMap,
} from '@/components/model-tree-select';
import { SelectWithSearch } from '@/components/originui/select-with-search';
import { RAGFlowFormItem } from '@/components/ragflow-form';
import { useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useOwnerTenantId } from '../../context';

export function GlobalVisionFormFields() {
  const { t } = useTranslation();
  const ownerTenantId = useOwnerTenantId();
  const enabled = useWatch({ name: 'enable_vision_enhancement' });
  return (
    <>
      <RAGFlowFormItem
        name="enable_vision_enhancement"
        label={t('flow.globalVisionEnhancement')}
        tooltip={t('flow.globalVisionEnhancementTip')}
      >
        {(field) => (
          <SelectWithSearch
            value={
              field.value === true
                ? 'enabled'
                : field.value === false
                  ? 'disabled'
                  : 'inherit'
            }
            onChange={(value) =>
              field.onChange(value === 'inherit' ? null : value === 'enabled')
            }
            options={[
              { label: t('flow.inheritVisionSettings'), value: 'inherit' },
              { label: t('flow.enableVisionEnhancement'), value: 'enabled' },
              { label: t('flow.disableVisionEnhancement'), value: 'disabled' },
            ]}
          />
        )}
      </RAGFlowFormItem>
      {enabled === true && (
        <ModelTreeSelectFormField
          name="vlm.llm_id"
          label={t('flow.globalVisionModel')}
          modelTypes={ModelTypeMap.img2txt_id}
          allowClear
          ownerTenantId={ownerTenantId}
        />
      )}
    </>
  );
}
