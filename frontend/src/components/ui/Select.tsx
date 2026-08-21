import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "../../lib/cn";

export type SelectOption = {
  label: string;
  value: string;
};

type SelectProps = {
  id: string;
  name?: string;
  value?: string;
  defaultValue?: string;
  placeholder: string;
  options: SelectOption[];
  disabled?: boolean;
  required?: boolean;
  className?: string;
  panelClassName?: string;
  onChange?: (value: string) => void;
  searchable?: boolean;
  searchPlaceholder?: string;
};

const Chevron = () => (
  <svg
    aria-hidden="true"
    viewBox="0 0 20 20"
    fill="none"
    className="h-5 w-5 text-text-primary"
  >
    <path
      d="M5 7.5L10 12.5L15 7.5"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const Select = ({
  id,
  name,
  value,
  defaultValue,
  placeholder,
  options,
  disabled = false,
  required = false,
  className,
  panelClassName,
  onChange,
  searchable = false,
  searchPlaceholder = "Search...",
}: SelectProps) => {
  const isControlled = value !== undefined;
  const [internalValue, setInternalValue] = useState(defaultValue ?? "");
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const hiddenInputRef = useRef<HTMLInputElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const selectedValue = isControlled ? value ?? "" : internalValue;

  const selectedLabel = useMemo(() => {
    if (!selectedValue) {
      return placeholder;
    }
    return options.find((option) => option.value === selectedValue)?.label ?? placeholder;
  }, [options, placeholder, selectedValue]);

  const filteredOptions = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!searchable || normalizedQuery.length === 0) {
      return options;
    }
    return options.filter((option) =>
      option.label.toLocaleLowerCase().includes(normalizedQuery),
    );
  }, [options, query, searchable]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    if (isOpen && searchable) {
      searchInputRef.current?.focus();
    }
    if (!isOpen) {
      setQuery("");
    }
  }, [isOpen, searchable]);

  const updateValue = (nextValue: string) => {
    if (!isControlled) {
      setInternalValue(nextValue);
    }
    if (hiddenInputRef.current) {
      hiddenInputRef.current.setCustomValidity(required && !nextValue ? "Please select an option." : "");
    }
    onChange?.(nextValue);
    setIsOpen(false);
    setQuery("");
  };

  return (
    <div className={cn("relative min-w-0", className)} ref={rootRef}>
      {name ? (
        <input
          ref={hiddenInputRef}
          type="text"
          tabIndex={-1}
          aria-hidden="true"
          name={name}
          value={selectedValue}
          onChange={() => undefined}
          required={required}
          className="pointer-events-none absolute h-0 w-0 opacity-0"
        />
      ) : null}
      <button
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={cn(
          "flex h-11 w-full items-center justify-between gap-3 rounded-md border border-input-border bg-input-bg px-3 text-left text-body text-text-primary",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
          "disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-text-muted",
        )}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className={cn("truncate", !selectedValue && "text-text-muted")}>
          {selectedLabel}
        </span>
        <Chevron />
      </button>
      {isOpen ? (
        <div
          className={cn(
            "absolute left-0 top-full z-20 mt-1 overflow-hidden rounded-md border border-border bg-surface-raised shadow-raised",
            "w-full min-w-full max-w-full",
            panelClassName,
          )}
        >
          {searchable ? (
            <div className="border-b border-border p-2">
              <input
                ref={searchInputRef}
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={searchPlaceholder}
                className="h-9 w-full rounded-md border border-input-border bg-input-bg px-2.5 text-body text-text-primary outline-none"
              />
            </div>
          ) : null}
          <ul className="max-h-80 overflow-y-auto py-1" role="listbox" aria-labelledby={id}>
            <li>
              <button
                type="button"
                className={cn(
                  "w-full px-3 py-2 text-left text-body text-text-primary hover:bg-surface-muted",
                  selectedValue === "" && "bg-surface-muted font-semibold",
                )}
                onClick={() => updateValue("")}
              >
                <span className="block truncate">{placeholder}</span>
              </button>
            </li>
            {filteredOptions.map((option) => (
              <li key={option.value}>
                <button
                  type="button"
                  className={cn(
                    "w-full px-3 py-2 text-left text-body text-text-primary hover:bg-surface-muted",
                    selectedValue === option.value && "bg-surface-muted font-semibold",
                  )}
                  onClick={() => updateValue(option.value)}
                >
                  <span className="block truncate">{option.label}</span>
                </button>
              </li>
            ))}
            {searchable && filteredOptions.length === 0 ? (
              <li className="px-3 py-2 text-small text-text-muted">
                No matching options.
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
};
