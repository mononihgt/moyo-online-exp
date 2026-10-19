import { Lock } from "lucide-react";
import { useState } from "react";

import type { DocumentType, QuestionnaireQuestion } from "../shared/types";
import { isProtectedQuestionType, isQuestionRequired } from "./questions";
import { isIdentityDocumentAnswer } from "./validation";

interface QuestionFieldProps {
  question: QuestionnaireQuestion;
  index: number;
  value: unknown;
  error?: string;
  disabled: boolean;
  onChange: (value: unknown) => void;
}

export default function QuestionField({
  question,
  index,
  value,
  error,
  disabled,
  onChange,
}: QuestionFieldProps) {
  const fieldId = `q-question-${index}`;
  const labelId = `${fieldId}-label`;
  const inputId = `${fieldId}-input`;
  const helpId = question.help ? `${fieldId}-help` : null;
  const errorId = error ? `${fieldId}-error` : null;
  const describedBy = joinIds([helpId, errorId]);
  const protectedQuestion = isProtectedQuestionType(question.type);
  const required = isQuestionRequired(question);

  const label = (
    <>
      {question.label}
      {required ? (
        protectedQuestion ? (
          <>
            <span className="q-required-lock" aria-hidden="true">
              <Lock size={13} aria-hidden="true" />
              必填
            </span>
            <span className="q-sr-only">（必填，不可取消）</span>
          </>
        ) : (
          <>
            <span className="q-required" aria-hidden="true">
              {" "}
              *
            </span>
            <span className="q-sr-only">（必填）</span>
          </>
        )
      ) : null}
    </>
  );

  const help = question.help ? (
    <p className="q-help" id={helpId ?? undefined}>
      {question.help}
    </p>
  ) : null;

  const errorMessage = error ? (
    <p className="q-question-error" id={errorId ?? undefined}>
      {error}
    </p>
  ) : null;

  if (question.type === "single_choice" || question.type === "multiple_choice") {
    const options = question.options ?? [];
    if (options.length === 0) {
      return (
        <div className="q-card q-card-error">
          <p className="q-question-label">{label}</p>
          {help}
          <p className="q-question-error">题目配置不完整，请联系主试。</p>
        </div>
      );
    }
    const selectedValues =
      question.type === "multiple_choice" && Array.isArray(value)
        ? value.filter((item): item is string => typeof item === "string")
        : [];
    return (
      <div className={`q-card${error ? " q-card-error" : ""}`}>
        <fieldset className="q-group" aria-describedby={describedBy}>
          <legend className="q-question-label" id={labelId}>
            {label}
          </legend>
          {help}
          <div className="q-options">
            {options.map((option, optionIndex) => {
              const selected =
                question.type === "single_choice"
                  ? value === option.value
                  : selectedValues.includes(option.value);
              return (
                <label
                  key={option.value}
                  className={`q-option${selected ? " selected" : ""}${disabled ? " q-option-disabled" : ""}`}
                >
                  <input
                    id={`${fieldId}-option-${optionIndex}`}
                    type={question.type === "single_choice" ? "radio" : "checkbox"}
                    name={question.id}
                    value={option.value}
                    checked={selected}
                    disabled={disabled}
                    onChange={(event) => {
                      if (question.type === "single_choice") {
                        onChange(option.value);
                        return;
                      }
                      const next = event.target.checked
                        ? [...selectedValues, option.value]
                        : selectedValues.filter((item) => item !== option.value);
                      onChange(next.length > 0 ? next : undefined);
                    }}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={describedBy}
                    aria-required={required || undefined}
                  />
                  <span>{option.label}</span>
                </label>
              );
            })}
          </div>
          {errorMessage}
        </fieldset>
      </div>
    );
  }

  if (question.type === "likert") {
    const min = question.min;
    const max = question.max;
    const validScale =
      typeof min === "number" &&
      typeof max === "number" &&
      Number.isInteger(min) &&
      Number.isInteger(max) &&
      min <= max &&
      max - min <= 100;
    if (!validScale) {
      return (
        <div className="q-card q-card-error">
          <p className="q-question-label">{label}</p>
          {help}
          <p className="q-question-error">题目配置不完整，请联系主试。</p>
        </div>
      );
    }
    const scale = Array.from({ length: max - min + 1 }, (_, offset) => min + offset);
    const hasScaleLabels = Boolean(question.minLabel || question.maxLabel);
    const scaleLabelsId = hasScaleLabels ? `${fieldId}-scale-labels` : null;
    const groupDescribedBy = joinIds([helpId, scaleLabelsId, errorId]);
    return (
      <div className={`q-card${error ? " q-card-error" : ""}`}>
        <div className="q-group">
          <p className="q-question-label" id={labelId}>
            {label}
          </p>
          {help}
          <div className="q-likert" role="group" aria-labelledby={labelId} aria-describedby={groupDescribedBy}>
            <div className="q-likert-options">
              {scale.map((point) => {
                const selected = value === point;
                return (
                  <button
                    key={point}
                    type="button"
                    className={`q-likert-option${selected ? " selected" : ""}`}
                    aria-pressed={selected}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={groupDescribedBy}
                    disabled={disabled}
                    onClick={() => onChange(point)}
                  >
                    {point}
                  </button>
                );
              })}
            </div>
            {hasScaleLabels ? (
              <div className="q-likert-labels" id={scaleLabelsId ?? undefined}>
                <span>{question.minLabel ?? ""}</span>
                <span>{question.maxLabel ?? ""}</span>
              </div>
            ) : null}
          </div>
          {errorMessage}
        </div>
      </div>
    );
  }

  if (question.type === "text") {
    return (
      <div className={`q-card${error ? " q-card-error" : ""}`}>
        <div className="q-group">
          <label className="q-question-label" htmlFor={inputId}>
            {label}
          </label>
          {help}
          <textarea
            id={inputId}
            className="q-text"
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy}
            aria-required={required || undefined}
          />
          {errorMessage}
        </div>
      </div>
    );
  }

  if (
    question.type === "short_text" ||
    question.type === "real_name" ||
    question.type === "alipay_phone"
  ) {
    const phone = question.type === "alipay_phone";
    return (
      <div className={`q-card${error ? " q-card-error" : ""}`}>
        <div className="q-group">
          <label className="q-question-label" htmlFor={inputId}>
            {label}
          </label>
          {help}
          <input
            id={inputId}
            className={`q-input${phone ? " q-input-phone" : ""}`}
            type={phone ? "tel" : "text"}
            inputMode={phone ? "tel" : undefined}
            autoComplete="off"
            maxLength={question.type === "short_text" ? question.maxLength : undefined}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy}
            aria-required={required || undefined}
          />
          {errorMessage}
        </div>
      </div>
    );
  }

  if (question.type === "identity_document") {
    const document = isIdentityDocumentAnswer(value) ? value : null;
    const documentType: DocumentType = document?.documentType ?? "id_card";
    const documentNumber = document?.number ?? "";
    const typeId = `${fieldId}-type`;
    return (
      <div className={`q-card${error ? " q-card-error" : ""}`}>
        <div
          className="q-group"
          role="group"
          aria-labelledby={labelId}
          aria-describedby={describedBy}
        >
          <p className="q-question-label" id={labelId}>
            {label}
          </p>
          {help}
          <div className="q-identity">
            <div className="q-field">
              <label className="q-field-label" htmlFor={typeId}>
                证件类型
              </label>
              <select
                id={typeId}
                className="q-select"
                value={documentType}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    documentType: event.target.value as DocumentType,
                    number: documentNumber,
                  })
                }
              >
                <option value="id_card">身份证</option>
                <option value="passport">护照</option>
              </select>
            </div>
            <div className="q-field q-field-grow">
              <label className="q-field-label" htmlFor={inputId}>
                证件号码
              </label>
              <input
                id={inputId}
                className="q-input"
                type="text"
                autoComplete="off"
                autoCapitalize="characters"
                value={documentNumber}
                disabled={disabled}
                onChange={(event) =>
                  onChange({ documentType, number: event.target.value })
                }
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy}
                aria-required={required || undefined}
              />
            </div>
          </div>
          {errorMessage}
        </div>
      </div>
    );
  }

  if (question.type === "number") {
    return (
      <div className={`q-card${error ? " q-card-error" : ""}`}>
        <div className="q-group">
          <label className="q-question-label" htmlFor={inputId}>
            {label}
          </label>
          {help}
          <NumberControl
            id={inputId}
            question={question}
            value={value}
            disabled={disabled}
            error={error}
            describedBy={describedBy}
            onChange={onChange}
          />
          {errorMessage}
        </div>
      </div>
    );
  }

  return (
    <div className="q-card q-card-error">
      <p className="q-question-label">{label}</p>
      {help}
      <p className="q-question-error">题目配置不完整，请联系主试。</p>
    </div>
  );
}

interface NumberControlProps {
  id: string;
  question: QuestionnaireQuestion;
  value: unknown;
  disabled: boolean;
  error?: string;
  describedBy?: string;
  onChange: (value: unknown) => void;
}

function NumberControl({ id, question, value, disabled, error, describedBy, onChange }: NumberControlProps) {
  const [text, setText] = useState(() => formatNumber(value));
  return (
    <input
      id={id}
      className="q-number"
      type="number"
      inputMode="decimal"
      step="any"
      min={question.min}
      max={question.max}
      value={text}
      disabled={disabled}
      onChange={(event) => {
        const raw = event.target.value;
        setText(raw);
        if (raw === "") {
          onChange(undefined);
          return;
        }
        const parsed = Number(raw);
        onChange(Number.isFinite(parsed) ? parsed : undefined);
      }}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy}
      aria-required={isQuestionRequired(question) || undefined}
    />
  );
}

function formatNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

function joinIds(ids: Array<string | null>): string | undefined {
  const joined = ids.filter((id): id is string => id !== null).join(" ");
  return joined === "" ? undefined : joined;
}
