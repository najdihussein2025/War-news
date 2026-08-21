import type { ConditionOption } from "../types";
import { Select } from "../../../components/ui";

type Props = {
  id: string;
  name?: string;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  required?: boolean;
  placeholder: string;
  loadingPlaceholder?: string;
  conditions: ConditionOption[];
  isLoading?: boolean;
  onChange?: (value: string) => void;
  className?: string;
};

export const ConditionSelect = ({
  id,
  name,
  value,
  defaultValue,
  disabled = false,
  required = false,
  placeholder,
  loadingPlaceholder = "Loading conditions...",
  conditions,
  isLoading = false,
  onChange,
  className,
}: Props) => (
  <Select
    id={id}
    name={name}
    required={required}
    value={value}
    defaultValue={defaultValue}
    disabled={disabled}
    placeholder={isLoading && conditions.length === 0 ? loadingPlaceholder : placeholder}
    options={conditions.map((item) => ({
      value: item.action_en,
      label: `${item.action_en} - ${item.action_ar}`,
    }))}
    className={className ?? "w-full min-w-0"}
    searchable
    searchPlaceholder="Search condition in English or Arabic"
    onChange={onChange}
  />
);
