import { useCallback, useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ClipboardList,
  Eye,
  Lock,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import type {
  ProtectedQuestionType,
  QuestionType,
  QuestionnaireOption,
  QuestionnaireSchema,
  QuestionnaireVersion,
} from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage } from "../api";
import type { QuestionnaireListResponse } from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  JsonDetails,
  LoadingBlock,
  PageHeader,
  StatusChip,
  VersionStatusChip,
  useUi,
} from "../ui";
import { QUESTION_TYPE_LABELS } from "../labels";

type Selection = string | "new" | null;

const PROTECTED_TYPES: ProtectedQuestionType[] = [
  "real_name",
  "alipay_phone",
  "identity_document",
];

function isProtectedType(type: QuestionType): type is ProtectedQuestionType {
  return type === "real_name" || type === "alipay_phone" || type === "identity_document";
}

const PROTECTED_DEFAULT_LABELS: Record<ProtectedQuestionType, string> = {
  real_name: "真实姓名",
  alipay_phone: "支付宝手机号",
  identity_document: "身份证明",
};

function defaultLabelForType(type: QuestionType): string {
  return isProtectedType(type) ? PROTECTED_DEFAULT_LABELS[type] : "";
}

interface DraftQuestion {
  id: string;
  type: QuestionType;
  label: string;
  required: boolean;
  options: QuestionnaireOption[];
  min: string;
  max: string;
  minLabel: string;
  maxLabel: string;
  maxLength: string;
  help: string;
}

interface DraftPage {
  id: string;
  questions: DraftQuestion[];
}

interface QuestionnaireDraft {
  name: string;
  title: string;
  description: string;
  pages: DraftPage[];
}

function uniqueId(prefix: string, existing: Set<string>): string {
  let index = existing.size + 1;
  let candidate = `${prefix}_${index}`;
  while (existing.has(candidate)) {
    index += 1;
    candidate = `${prefix}_${index}`;
  }
  return candidate;
}

function allQuestionIds(draft: QuestionnaireDraft): Set<string> {
  return new Set(
    draft.pages.flatMap((page) => page.questions.map((question) => question.id)),
  );
}

function allPageIds(draft: QuestionnaireDraft): Set<string> {
  return new Set(draft.pages.map((page) => page.id));
}

function newQuestion(id: string, type: QuestionType = "text"): DraftQuestion {
  return {
    id,
    type,
    label: defaultLabelForType(type),
    required: true,
    options:
      type === "single_choice" || type === "multiple_choice"
        ? [
            { value: "", label: "" },
            { value: "", label: "" },
          ]
        : [],
    min: type === "likert" ? "1" : "",
    max: type === "likert" ? "5" : "",
    minLabel: "",
    maxLabel: "",
    maxLength: "",
    help: "",
  };
}

function emptyDraft(): QuestionnaireDraft {
  const question = newQuestion("q_1", "single_choice");
  return {
    name: "",
    title: "",
    description: "",
    pages: [{ id: "page_1", questions: [question] }],
  };
}

function draftFromVersion(version: QuestionnaireVersion): QuestionnaireDraft {
  return {
    name: version.name,
    title: version.schema.title,
    description: version.schema.description ?? "",
    pages: version.schema.pages.map((page) => ({
      id: page.id,
      questions: page.questions.map((question) => ({
        id: question.id,
        type: question.type,
        label: question.label,
        required: question.required,
        options: (question.options ?? []).map((option) => ({ ...option })),
        min: question.min === undefined || question.min === null ? "" : String(question.min),
        max: question.max === undefined || question.max === null ? "" : String(question.max),
        minLabel: question.minLabel ?? "",
        maxLabel: question.maxLabel ?? "",
        maxLength:
          question.maxLength === undefined || question.maxLength === null
            ? ""
            : String(question.maxLength),
        help: question.help ?? "",
      })),
    })),
  };
}

function parseOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseOptionalInteger(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) ? parsed : null;
}

function protectedTypeCount(draft: QuestionnaireDraft, type: ProtectedQuestionType): number {
  return draft.pages.reduce(
    (total, page) =>
      total + page.questions.filter((question) => question.type === type).length,
    0,
  );
}

function protectedIssueMessages(draft: QuestionnaireDraft): string[] {
  return PROTECTED_TYPES.flatMap((type) => {
    const count = protectedTypeCount(draft, type);
    const label = QUESTION_TYPE_LABELS[type] ?? type;
    if (count === 0) return [`缺少受保护字段：${label}`];
    if (count > 1) return [`受保护字段重复：${label}（${count} 题）`];
    return [];
  });
}

function protectedCoveredCount(draft: QuestionnaireDraft): number {
  return PROTECTED_TYPES.filter((type) => protectedTypeCount(draft, type) === 1).length;
}

function buildQuestionnairePayload(draft: QuestionnaireDraft): {
  name: string;
  schema: QuestionnaireSchema;
  errors: string[];
} {
  const errors: string[] = [];
  const name = draft.name.trim();
  if (!name) errors.push("请填写版本名称");
  const title = draft.title.trim();
  if (!title) errors.push("请填写问卷标题");
  if (draft.pages.length === 0) errors.push("问卷至少需要一个页面");
  const seenPages = new Set<string>();
  const seenQuestions = new Set<string>();
  const pages = draft.pages.map((page, pageIndex) => {
    const pageId = page.id.trim();
    if (!pageId) {
      errors.push(`第 ${pageIndex + 1} 页的页面 id 不能为空`);
    } else if (seenPages.has(pageId)) {
      errors.push(`页面 id 重复：${pageId}`);
    }
    seenPages.add(pageId);
    if (page.questions.length === 0) {
      errors.push(`第 ${pageIndex + 1} 页至少需要一道题目`);
    }
    const questions = page.questions.map((question, questionIndex) => {
      const prefix = `第 ${pageIndex + 1} 页第 ${questionIndex + 1} 题`;
      const questionId = question.id.trim();
      if (!questionId) {
        errors.push(`${prefix}的题目 id 不能为空`);
      } else if (seenQuestions.has(questionId)) {
        errors.push(`题目 id 重复：${questionId}`);
      }
      seenQuestions.add(questionId);
      const label = question.label.trim();
      if (!label) errors.push(`${prefix}的题干不能为空`);
      const base: QuestionnaireSchema["pages"][number]["questions"][number] = {
        id: questionId,
        type: question.type,
        label,
        required: isProtectedType(question.type) ? true : question.required,
      };
      if (question.type === "single_choice" || question.type === "multiple_choice") {
        if (question.options.length < 2) {
          errors.push(`${prefix}至少需要两个选项`);
        }
        const seenValues = new Set<string>();
        const options: QuestionnaireOption[] = [];
        question.options.forEach((option, optionIndex) => {
          const value = option.value.trim();
          const optionLabel = option.label.trim();
          if (!value) errors.push(`${prefix}第 ${optionIndex + 1} 个选项的值不能为空`);
          if (!optionLabel) errors.push(`${prefix}第 ${optionIndex + 1} 个选项的文案不能为空`);
          if (value && seenValues.has(value)) {
            errors.push(`${prefix}的选项值重复：${value}`);
          }
          seenValues.add(value);
          if (value && optionLabel) options.push({ value, label: optionLabel });
        });
        base.options = options;
      }
      if (question.type === "likert") {
        const minimum = parseOptionalInteger(question.min);
        const maximum = parseOptionalInteger(question.max);
        if (minimum === null || maximum === null || minimum >= maximum) {
          errors.push(`${prefix}的李克特量表需要整数 min < max`);
        } else {
          base.min = minimum;
          base.max = maximum;
        }
        const minLabel = question.minLabel.trim();
        const maxLabel = question.maxLabel.trim();
        if (minLabel) base.minLabel = minLabel;
        if (maxLabel) base.maxLabel = maxLabel;
      }
      if (question.type === "number") {
        const minimum = parseOptionalNumber(question.min);
        const maximum = parseOptionalNumber(question.max);
        if (question.min.trim() !== "" && minimum === null) {
          errors.push(`${prefix}的最小值必须是数字`);
        }
        if (question.max.trim() !== "" && maximum === null) {
          errors.push(`${prefix}的最大值必须是数字`);
        }
        if (minimum !== null && maximum !== null && minimum > maximum) {
          errors.push(`${prefix}的最小值不能大于最大值`);
        }
        if (minimum !== null) base.min = minimum;
        if (maximum !== null) base.max = maximum;
      }
      if (question.type === "short_text") {
        const maxLength = parseOptionalInteger(question.maxLength);
        if (question.maxLength.trim() !== "") {
          if (maxLength === null || maxLength <= 0) {
            errors.push(`${prefix}的最大字数必须是正整数`);
          } else {
            base.maxLength = maxLength;
          }
        }
      }
      const help = question.help.trim();
      if (help) base.help = help;
      return base;
    });
    return { id: pageId, questions };
  });
  if (errors.length > 0) {
    return { name, schema: { title, pages: [] }, errors };
  }
  const schema: QuestionnaireSchema = { title, pages };
  const description = draft.description.trim();
  if (description) schema.description = description;
  return { name, schema, errors: [] };
}

function QuestionPreviewItem({ question }: { question: DraftQuestion }) {
  const min = parseOptionalInteger(question.min);
  const max = parseOptionalInteger(question.max);
  return (
    <div className="q-item">
      <div className="q-label">
        {question.label || "（未填写题干）"}
        {question.required ? <span className="q-required">*</span> : null}
      </div>
      {question.help.trim() ? <div className="q-help">{question.help}</div> : null}
      {isProtectedType(question.type) ? (
        <div className="q-protected">
          <Lock size={12} />
          受保护字段 · 必填
        </div>
      ) : null}
      {question.type === "single_choice" || question.type === "multiple_choice" ? (
        <div className="q-options">
          {question.options.map((option, index) => (
            <label className="q-option" key={index}>
              <input
                type={question.type === "single_choice" ? "radio" : "checkbox"}
                disabled
                aria-label={option.label || `选项 ${index + 1}`}
              />
              <span>{option.label || option.value || `选项 ${index + 1}`}</span>
            </label>
          ))}
        </div>
      ) : null}
      {question.type === "likert" && min !== null && max !== null && min < max ? (
        <div>
          <div className="q-scale">
            {Array.from({ length: Math.min(max - min + 1, 30) }, (_, index) => (
              <span key={index}>{min + index}</span>
            ))}
            {max - min + 1 > 30 ? <span>… {max}</span> : null}
          </div>
          {question.minLabel || question.maxLabel ? (
            <div className="q-scale-labels">
              <span>{question.minLabel}</span>
              <span>{question.maxLabel}</span>
            </div>
          ) : null}
        </div>
      ) : null}
      {question.type === "text" ? (
        <textarea disabled aria-label="文本输入预览" rows={3} />
      ) : null}
      {question.type === "short_text" ? (
        <input
          type="text"
          disabled
          aria-label="单行填空预览"
          maxLength={parseOptionalInteger(question.maxLength) ?? undefined}
        />
      ) : null}
      {question.type === "number" ? (
        <input type="number" disabled aria-label="数字输入预览" />
      ) : null}
      {question.type === "real_name" ? (
        <input type="text" disabled aria-label="真实姓名输入预览" placeholder="真实姓名" />
      ) : null}
      {question.type === "alipay_phone" ? (
        <input type="tel" disabled aria-label="支付宝手机号输入预览" placeholder="支付宝手机号" />
      ) : null}
      {question.type === "identity_document" ? (
        <div className="q-identity-preview">
          <select disabled aria-label="证件类型预览">
            <option>身份证</option>
            <option>护照</option>
          </select>
          <input type="text" disabled aria-label="证件号码预览" placeholder="证件号码" />
        </div>
      ) : null}
    </div>
  );
}

function QuestionnairePreview({ draft }: { draft: QuestionnaireDraft }) {
  return (
    <div className="admin-question-preview">
      <h3>{draft.title || "（未填写问卷标题）"}</h3>
      {draft.description.trim() ? <div className="q-subtitle">{draft.description}</div> : null}
      {draft.pages.map((page, pageIndex) => (
        <div className="q-page" key={pageIndex}>
          <div className="admin-question-id" style={{ marginBottom: "8px" }}>
            第 {pageIndex + 1} 页 · {page.id || "（无页面 id）"}
          </div>
          {page.questions.length === 0 ? (
            <div className="admin-hint">本页暂无题目。</div>
          ) : (
            page.questions.map((question, questionIndex) => (
              <QuestionPreviewItem key={questionIndex} question={question} />
            ))
          )}
        </div>
      ))}
      {draft.pages.length === 0 ? <div className="admin-hint">暂无页面。</div> : null}
    </div>
  );
}

export function QuestionnairesPage() {
  const { notify, confirm } = useUi();
  const [versions, setVersions] = useState<QuestionnaireVersion[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [draft, setDraft] = useState<QuestionnaireDraft>(() => emptyDraft());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const selected =
    selection !== "new" && selection !== null
      ? versions.find((version) => version.id === selection) ?? null
      : null;
  const isNew = selection === "new";
  const readOnly = selected !== null && selected.status !== "draft";

  const applyVersion = useCallback((version: QuestionnaireVersion | null) => {
    if (version === null) {
      setSelection(null);
      setDraft(emptyDraft());
      return;
    }
    setSelection(version.id);
    setDraft(draftFromVersion(version));
    setValidationErrors([]);
    setSaveError(null);
  }, []);

  const loadVersions = useCallback(
    async (preferredId?: string) => {
      const response = await adminApi.get<QuestionnaireListResponse>("/questionnaires");
      setVersions(response.questionnaires);
      const targetId = preferredId ?? (selection !== "new" ? selection : null);
      if (targetId) {
        const version = response.questionnaires.find((item) => item.id === targetId);
        applyVersion(version ?? null);
      } else if (selection === null) {
        const preferred =
          response.questionnaires.find((item) => item.status === "published") ??
          response.questionnaires[0] ??
          null;
        applyVersion(preferred);
      }
    },
    [selection, applyVersion],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const response = await adminApi.get<QuestionnaireListResponse>("/questionnaires");
        if (cancelled) return;
        setVersions(response.questionnaires);
        const preferred =
          response.questionnaires.find((item) => item.status === "published") ??
          response.questionnaires[0] ??
          null;
        applyVersion(preferred);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // 首次进入时加载问卷版本
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startNew() {
    setSelection("new");
    setDraft(emptyDraft());
    setValidationErrors([]);
    setSaveError(null);
  }

  function updateQuestion(
    pageIndex: number,
    questionIndex: number,
    patch: Partial<DraftQuestion>,
  ) {
    setDraft((current) => ({
      ...current,
      pages: current.pages.map((page, pIndex) =>
        pIndex === pageIndex
          ? {
              ...page,
              questions: page.questions.map((question, qIndex) =>
                qIndex === questionIndex ? { ...question, ...patch } : question,
              ),
            }
          : page,
      ),
    }));
  }

  function protectedTypeUsedElsewhere(
    type: ProtectedQuestionType,
    pageIndex: number,
    questionIndex: number,
  ): boolean {
    return draft.pages.some((page, pIndex) =>
      page.questions.some(
        (question, qIndex) =>
          !(pIndex === pageIndex && qIndex === questionIndex) && question.type === type,
      ),
    );
  }

  function changeQuestionType(pageIndex: number, questionIndex: number, type: QuestionType) {
    if (isProtectedType(type)) {
      const alreadyUsed = draft.pages.some((page, pIndex) =>
        page.questions.some(
          (question, qIndex) =>
            !(pIndex === pageIndex && qIndex === questionIndex) &&
            question.type === type,
        ),
      );
      if (alreadyUsed) {
        notify(
          `受保护字段「${PROTECTED_DEFAULT_LABELS[type]}」已存在，每种受保护类型只能有一题`,
          "error",
        );
        return;
      }
    }
    setDraft((current) => ({
      ...current,
      pages: current.pages.map((page, pIndex) =>
        pIndex === pageIndex
          ? {
              ...page,
              questions: page.questions.map((question, qIndex) => {
                if (qIndex !== questionIndex) return question;
                return {
                  ...question,
                  type,
                  required: isProtectedType(type) ? true : question.required,
                  label: question.label.trim()
                    ? question.label
                    : defaultLabelForType(type),
                  options:
                    (type === "single_choice" || type === "multiple_choice") &&
                    question.options.length < 2
                      ? [
                          { value: "", label: "" },
                          { value: "", label: "" },
                        ]
                      : question.options,
                  min: type === "likert" ? question.min || "1" : question.min,
                  max: type === "likert" ? question.max || "5" : question.max,
                };
              }),
            }
          : page,
      ),
    }));
  }

  function addPage() {
    setDraft((current) => {
      const pageId = uniqueId("page", allPageIds(current));
      const questionId = uniqueId("q", allQuestionIds(current));
      return {
        ...current,
        pages: [
          ...current.pages,
          {
            id: pageId,
            questions: [newQuestion(questionId, "text")],
          },
        ],
      };
    });
  }

  async function removePage(pageIndex: number) {
    if (draft.pages.length <= 1) {
      notify("问卷至少需要一个页面", "error");
      return;
    }
    const ok = await confirm({
      title: "删除页面",
      message: `确认删除第 ${pageIndex + 1} 页及其 ${draft.pages[pageIndex]?.questions.length ?? 0} 道题目？`,
      confirmLabel: "删除页面",
      danger: true,
    });
    if (!ok) return;
    setDraft((current) => ({
      ...current,
      pages: current.pages.filter((_, index) => index !== pageIndex),
    }));
  }

  function movePage(pageIndex: number, direction: -1 | 1) {
    setDraft((current) => {
      const target = pageIndex + direction;
      if (target < 0 || target >= current.pages.length) return current;
      const pages = [...current.pages];
      [pages[pageIndex], pages[target]] = [pages[target], pages[pageIndex]];
      return { ...current, pages };
    });
  }

  function addQuestion(pageIndex: number) {
    setDraft((current) => {
      const questionId = uniqueId("q", allQuestionIds(current));
      return {
        ...current,
        pages: current.pages.map((page, index) =>
          index === pageIndex
            ? { ...page, questions: [...page.questions, newQuestion(questionId)] }
            : page,
        ),
      };
    });
  }

  async function removeQuestion(pageIndex: number, questionIndex: number) {
    const question = draft.pages[pageIndex]?.questions[questionIndex];
    const ok = await confirm({
      title: "删除题目",
      message: `确认删除题目「${question?.label || question?.id || questionIndex + 1}」？`,
      confirmLabel: "删除题目",
      danger: true,
    });
    if (!ok) return;
    setDraft((current) => ({
      ...current,
      pages: current.pages.map((page, index) =>
        index === pageIndex
          ? {
              ...page,
              questions: page.questions.filter((_, qIndex) => qIndex !== questionIndex),
            }
          : page,
      ),
    }));
  }

  function moveQuestion(pageIndex: number, questionIndex: number, direction: -1 | 1) {
    setDraft((current) => ({
      ...current,
      pages: current.pages.map((page, index) => {
        if (index !== pageIndex) return page;
        const target = questionIndex + direction;
        if (target < 0 || target >= page.questions.length) return page;
        const questions = [...page.questions];
        [questions[questionIndex], questions[target]] = [
          questions[target],
          questions[questionIndex],
        ];
        return { ...page, questions };
      }),
    }));
  }

  function addOption(pageIndex: number, questionIndex: number) {
    const question = draft.pages[pageIndex]?.questions[questionIndex];
    if (!question) return;
    updateQuestion(pageIndex, questionIndex, {
      options: [...question.options, { value: "", label: "" }],
    });
  }

  function updateOption(
    pageIndex: number,
    questionIndex: number,
    optionIndex: number,
    patch: Partial<QuestionnaireOption>,
  ) {
    const question = draft.pages[pageIndex]?.questions[questionIndex];
    if (!question) return;
    updateQuestion(pageIndex, questionIndex, {
      options: question.options.map((option, index) =>
        index === optionIndex ? { ...option, ...patch } : option,
      ),
    });
  }

  function removeOption(pageIndex: number, questionIndex: number, optionIndex: number) {
    const question = draft.pages[pageIndex]?.questions[questionIndex];
    if (!question) return;
    if (question.options.length <= 2) {
      notify("单选或多选至少需要两个选项", "error");
      return;
    }
    updateQuestion(pageIndex, questionIndex, {
      options: question.options.filter((_, index) => index !== optionIndex),
    });
  }

  async function persistDraft(showNotice: boolean): Promise<string | null> {
    const result = buildQuestionnairePayload(draft);
    setValidationErrors(result.errors);
    if (result.errors.length > 0) {
      setSaveError(null);
      notify("请先修正问卷配置错误", "error");
      return null;
    }
    setSaving(true);
    setSaveError(null);
    try {
      if (isNew || selection === null) {
        const response = await adminApi.post<{ questionnaire: QuestionnaireVersion }>(
          "/questionnaires",
          { name: result.name, schemaJson: result.schema },
        );
        await loadVersions(response.questionnaire.id);
        if (showNotice) notify(`问卷草稿已创建，版本 ${response.questionnaire.version}`);
        return response.questionnaire.id;
      }
      const response = await adminApi.patch<{ questionnaire: QuestionnaireVersion }>(
        `/questionnaires/${selection}`,
        { name: result.name, schemaJson: result.schema },
      );
      await loadVersions(response.questionnaire.id);
      if (showNotice) notify("问卷草稿已保存");
      return response.questionnaire.id;
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    await persistDraft(true);
  }

  async function handlePublish() {
    const result = buildQuestionnairePayload(draft);
    setValidationErrors(result.errors);
    if (result.errors.length > 0) {
      notify("请先修正问卷配置错误", "error");
      return;
    }
    const protectedIssues = protectedIssueMessages(draft);
    if (protectedIssues.length > 0) {
      notify(protectedIssues.join("；"), "error");
      return;
    }
    const ok = await confirm({
      title: "发布问卷版本",
      message:
        "发布后同名已发布的问卷会归档，新进入房间的参与者将使用该版本。发布后本版本不可修改。",
      confirmLabel: "发布",
    });
    if (!ok) return;
    setPublishing(true);
    setSaveError(null);
    try {
      const id = await persistDraft(false);
      if (!id) return;
      await adminApi.post(`/questionnaires/${id}/publish`);
      await loadVersions(id);
      notify("问卷版本已发布");
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setPublishing(false);
    }
  }

  const pageCount = draft.pages.length;
  const questionCount = draft.pages.reduce((total, page) => total + page.questions.length, 0);
  const draftJSON = buildQuestionnairePayload(draft);
  const protectedIssues = protectedIssueMessages(draft);
  const protectedCovered = protectedCoveredCount(draft);
  const publishBlocked = protectedIssues.length > 0;
  const editorTitle = isNew
    ? "新建问卷"
    : selected
      ? `${selected.name} · 第 ${selected.version} 版`
      : "问卷编辑器";

  return (
    <div>
      <PageHeader
        title="问卷"
        subtitle="按页面组织题目，支持单选、多选、李克特量表、文本、单行填空、数字与三种受保护身份字段。发布后的版本只读。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={startNew}
            data-testid="questionnaire-create"
          >
            <Plus size={16} />
            新建问卷
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void loadVersions()} /> : null}

      {loading ? (
        <LoadingBlock rows={6} label="正在加载问卷版本" />
      ) : versions.length === 0 && selection !== "new" ? (
        <EmptyState
          icon={ClipboardList}
          title="尚未创建问卷"
          description="创建并发布问卷版本后，才能在创建 Room 时选择。"
          action={
            <button type="button" className="admin-btn admin-btn-primary" onClick={startNew}>
              新建问卷
            </button>
          }
        />
      ) : (
        <div className="admin-layout-columns">
          <aside className="admin-card admin-sticky-side">
            <h2 className="admin-section-title">版本列表</h2>
            <div className="admin-version-list">
              {versions.map((version) => (
                <button
                  type="button"
                  key={version.id}
                  className={`admin-version-item${selection === version.id ? " active" : ""}`}
                  onClick={() => applyVersion(version)}
                  data-testid={`questionnaire-version-${version.id}`}
                >
                  <div className="admin-version-item-head">
                    <span>
                      {version.name} · v{version.version}
                    </span>
                    <VersionStatusChip status={version.status} />
                  </div>
                  <div className="admin-version-item-meta">{version.schema.title}</div>
                  <div className="admin-version-item-meta">
                    {version.schema.pages.length} 页 ·{" "}
                    {version.schema.pages.reduce(
                      (total, page) => total + page.questions.length,
                      0,
                    )}{" "}
                    题
                  </div>
                  <div className="admin-version-item-meta">
                    发布：{formatDateTime(version.publishedAt)}
                  </div>
                </button>
              ))}
              {isNew ? (
                <div className="admin-version-item active" style={{ cursor: "default" }}>
                  <div className="admin-version-item-head">
                    <span>新草稿</span>
                    <StatusChip>未保存</StatusChip>
                  </div>
                  <div className="admin-version-item-meta">保存后生成版本号</div>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="admin-card">
            <div className="admin-questionnaire-editor-head">
              <div>
                <h2 className="admin-section-title" style={{ marginBottom: "4px" }}>
                  {editorTitle}
                </h2>
                <div className="admin-chip-list">
                  {selected ? <VersionStatusChip status={selected.status} /> : null}
                  {selected?.publishedAt ? (
                    <span className="admin-hint">发布于 {formatDateTime(selected.publishedAt)}</span>
                  ) : null}
                  <span className="admin-hint">
                    {pageCount} 页 · {questionCount} 题
                  </span>
                  <span
                    className={`admin-chip${
                      protectedCovered === PROTECTED_TYPES.length ? " admin-chip-success" : ""
                    }`}
                  >
                    受保护字段 {protectedCovered}/3
                  </span>
                </div>
              </div>
              <div className="admin-btn-row">
                {readOnly ? (
                  <span className="admin-hint">
                    <Lock size={13} style={{ verticalAlign: "-2px", marginRight: "4px" }} />
                    已发布版本只读
                  </span>
                ) : (
                  <>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => void handleSave()}
                      disabled={saving || publishing}
                      data-testid="questionnaire-save"
                    >
                      <Save size={15} />
                      {saving ? "保存中" : "保存草稿"}
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={saving || publishing || publishBlocked}
                      title={publishBlocked ? protectedIssues.join("；") : undefined}
                      data-testid="questionnaire-publish"
                    >
                      <CheckCircle2 size={15} />
                      {publishing ? "发布中" : "发布"}
                    </button>
                  </>
                )}
              </div>
            </div>

            {validationErrors.length > 0 ? (
              <InlineNotice tone="error">
                <ul className="admin-validation-list">
                  {validationErrors.map((message, index) => (
                    <li key={`${message}-${index}`}>{message}</li>
                  ))}
                </ul>
              </InlineNotice>
            ) : null}
            {saveError ? <InlineNotice tone="error">{saveError}</InlineNotice> : null}
            {!readOnly && protectedIssues.length > 0 ? (
              <InlineNotice tone="warning">
                <div data-testid="questionnaire-protected-status">
                  发布前需要真实姓名、支付宝手机号、身份证明各恰好一题，且始终必填。
                  <ul className="admin-validation-list">
                    {protectedIssues.map((message) => (
                      <li key={message}>{message}</li>
                    ))}
                  </ul>
                </div>
              </InlineNotice>
            ) : null}

            {readOnly ? (
              <div className="admin-stack">
                <div className="admin-readonly-banner">
                  <Lock size={14} />
                  该版本已发布或归档，配置只读。如需调整，请新建草稿并发布新版本。
                </div>
                <dl className="admin-detail-list">
                  <div>
                    <dt>版本名称</dt>
                    <dd>{selected?.name}</dd>
                  </div>
                  <div>
                    <dt>问卷标题</dt>
                    <dd>{selected?.schema.title}</dd>
                  </div>
                  <div>
                    <dt>页面 / 题目</dt>
                    <dd>
                      {selected?.schema.pages.length} 页 /{" "}
                      {selected?.schema.pages.reduce(
                        (total, page) => total + page.questions.length,
                        0,
                      )}{" "}
                      题
                    </dd>
                  </div>
                </dl>
                <QuestionnairePreview draft={draft} />
                {selected ? (
                  <JsonDetails value={selected.schema} label="查看问卷 schema JSON" />
                ) : null}
              </div>
            ) : (
              <div className="admin-split-editor">
                <div>
                  <div className="admin-form-row">
                    <Field label="版本名称" htmlFor="questionnaire-name">
                      <input
                        id="questionnaire-name"
                        className="admin-input"
                        value={draft.name}
                        onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                        placeholder="例如：正式问卷"
                        data-testid="questionnaire-name"
                      />
                    </Field>
                    <Field label="问卷标题" htmlFor="questionnaire-title">
                      <input
                        id="questionnaire-title"
                        className="admin-input"
                        value={draft.title}
                        onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                        data-testid="questionnaire-title"
                      />
                    </Field>
                  </div>
                  <Field label="问卷说明" htmlFor="questionnaire-description">
                    <textarea
                      id="questionnaire-description"
                      className="admin-textarea"
                      value={draft.description}
                      onChange={(event) =>
                        setDraft({ ...draft, description: event.target.value })
                      }
                      style={{ minHeight: "72px" }}
                      data-testid="questionnaire-description"
                    />
                  </Field>

                  {draft.pages.map((page, pageIndex) => (
                    <div className="admin-page-editor-row" key={`page-${pageIndex}`}>
                      <div className="admin-page-editor-head">
                        <h3>第 {pageIndex + 1} 页</h3>
                        <div className="admin-inline-actions">
                          <button
                            type="button"
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                            onClick={() => movePage(pageIndex, -1)}
                            disabled={pageIndex === 0}
                            aria-label="上移页面"
                          >
                            <ArrowUp size={14} />
                          </button>
                          <button
                            type="button"
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                            onClick={() => movePage(pageIndex, 1)}
                            disabled={pageIndex === draft.pages.length - 1}
                            aria-label="下移页面"
                          >
                            <ArrowDown size={14} />
                          </button>
                          <button
                            type="button"
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                            onClick={() => void removePage(pageIndex)}
                            aria-label="删除页面"
                            data-testid={`questionnaire-remove-page-${pageIndex}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                      <Field
                        label="页面 id"
                        htmlFor={`questionnaire-page-id-${pageIndex}`}
                        hint="同一问卷内必须唯一。"
                      >
                        <input
                          id={`questionnaire-page-id-${pageIndex}`}
                          className="admin-input"
                          value={page.id}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              pages: current.pages.map((item, index) =>
                                index === pageIndex ? { ...item, id: event.target.value } : item,
                              ),
                            }))
                          }
                          data-testid={`questionnaire-page-id-${pageIndex}`}
                        />
                      </Field>

                      {page.questions.map((question, questionIndex) => (
                        <div
                          className="admin-question-editor"
                          key={`question-${pageIndex}-${questionIndex}`}
                          data-testid={`questionnaire-question-${pageIndex}-${questionIndex}`}
                        >
                          <div className="admin-question-editor-head">
                            <span>
                              第 {questionIndex + 1} 题
                              <span className="admin-question-id" style={{ marginLeft: "8px" }}>
                                {question.id}
                              </span>
                            </span>
                            <div className="admin-inline-actions">
                              <button
                                type="button"
                                className="admin-btn admin-btn-ghost admin-btn-sm"
                                onClick={() => moveQuestion(pageIndex, questionIndex, -1)}
                                disabled={questionIndex === 0}
                                aria-label="上移题目"
                              >
                                <ArrowUp size={14} />
                              </button>
                              <button
                                type="button"
                                className="admin-btn admin-btn-ghost admin-btn-sm"
                                onClick={() => moveQuestion(pageIndex, questionIndex, 1)}
                                disabled={questionIndex === page.questions.length - 1}
                                aria-label="下移题目"
                              >
                                <ArrowDown size={14} />
                              </button>
                              <button
                                type="button"
                                className="admin-btn admin-btn-ghost admin-btn-sm"
                                onClick={() => void removeQuestion(pageIndex, questionIndex)}
                                aria-label="删除题目"
                                data-testid={`questionnaire-remove-question-${pageIndex}-${questionIndex}`}
                              >
                                <Trash2 size={14} />
                              </button>
                            </div>
                          </div>
                          <div className="admin-form-row admin-form-row-3">
                            <Field
                              label="题目 id"
                              htmlFor={`questionnaire-question-id-${pageIndex}-${questionIndex}`}
                            >
                              <input
                                id={`questionnaire-question-id-${pageIndex}-${questionIndex}`}
                                className="admin-input"
                                value={question.id}
                                onChange={(event) =>
                                  updateQuestion(pageIndex, questionIndex, {
                                    id: event.target.value,
                                  })
                                }
                                data-testid={`questionnaire-question-id-${pageIndex}-${questionIndex}`}
                              />
                            </Field>
                            <Field
                              label="题型"
                              htmlFor={`questionnaire-question-type-${pageIndex}-${questionIndex}`}
                              hint={
                                isProtectedType(question.type)
                                  ? "受保护字段会加密存储。"
                                  : undefined
                              }
                            >
                              <select
                                id={`questionnaire-question-type-${pageIndex}-${questionIndex}`}
                                className="admin-select"
                                value={question.type}
                                onChange={(event) =>
                                  changeQuestionType(
                                    pageIndex,
                                    questionIndex,
                                    event.target.value as QuestionType,
                                  )
                                }
                                data-testid={`questionnaire-question-type-${pageIndex}-${questionIndex}`}
                              >
                                {(Object.keys(QUESTION_TYPE_LABELS) as QuestionType[]).map(
                                  (type) => {
                                    const takenElsewhere =
                                      isProtectedType(type) &&
                                      protectedTypeUsedElsewhere(
                                        type,
                                        pageIndex,
                                        questionIndex,
                                      );
                                    return (
                                      <option key={type} value={type} disabled={takenElsewhere}>
                                        {QUESTION_TYPE_LABELS[type]}
                                        {takenElsewhere ? "（已使用）" : ""}
                                      </option>
                                    );
                                  },
                                )}
                              </select>
                            </Field>
                            <Field
                              label={
                                isProtectedType(question.type)
                                  ? "必答（受保护字段）"
                                  : "必答"
                              }
                            >
                              <label className="admin-check-item">
                                <input
                                  type="checkbox"
                                  checked={
                                    isProtectedType(question.type)
                                      ? true
                                      : question.required
                                  }
                                  disabled={isProtectedType(question.type)}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      required: event.target.checked,
                                    })
                                  }
                                  data-testid={`questionnaire-required-${pageIndex}-${questionIndex}`}
                                />
                                <span>
                                  {isProtectedType(question.type) ? (
                                    <>
                                      <Lock
                                        size={12}
                                        style={{ verticalAlign: "-2px", marginRight: "4px" }}
                                      />
                                      受保护字段始终必填
                                    </>
                                  ) : (
                                    "参与者必须回答"
                                  )}
                                </span>
                              </label>
                            </Field>
                          </div>
                          <Field
                            label="题干"
                            htmlFor={`questionnaire-question-label-${pageIndex}-${questionIndex}`}
                          >
                            <input
                              id={`questionnaire-question-label-${pageIndex}-${questionIndex}`}
                              className="admin-input"
                              value={question.label}
                              onChange={(event) =>
                                updateQuestion(pageIndex, questionIndex, {
                                  label: event.target.value,
                                })
                              }
                              data-testid={`questionnaire-question-label-${pageIndex}-${questionIndex}`}
                            />
                          </Field>
                          <Field
                            label="帮助文本（可选）"
                            htmlFor={`questionnaire-question-help-${pageIndex}-${questionIndex}`}
                          >
                            <input
                              id={`questionnaire-question-help-${pageIndex}-${questionIndex}`}
                              className="admin-input"
                              value={question.help}
                              onChange={(event) =>
                                updateQuestion(pageIndex, questionIndex, {
                                  help: event.target.value,
                                })
                              }
                            />
                          </Field>

                          {isProtectedType(question.type) ? (
                            <div className="admin-protected-hint">
                              <Lock size={13} />
                              受保护字段会加密存储，始终必填；每种受保护类型每份问卷只能有一题。
                            </div>
                          ) : null}

                          {question.type === "short_text" ? (
                            <div className="admin-form-row">
                              <Field
                                label="最大字数（可选）"
                                htmlFor={`questionnaire-question-max-length-${pageIndex}-${questionIndex}`}
                                hint="留空表示不限制。"
                              >
                                <input
                                  id={`questionnaire-question-max-length-${pageIndex}-${questionIndex}`}
                                  className="admin-input"
                                  type="number"
                                  min="1"
                                  step="1"
                                  value={question.maxLength}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      maxLength: event.target.value,
                                    })
                                  }
                                  data-testid={`questionnaire-question-max-length-${pageIndex}-${questionIndex}`}
                                />
                              </Field>
                            </div>
                          ) : null}

                          {question.type === "single_choice" ||
                          question.type === "multiple_choice" ? (
                            <div style={{ marginTop: "12px" }}>
                              <div className="admin-label">选项</div>
                              {question.options.map((option, optionIndex) => (
                                <div
                                  className="admin-option-row"
                                  key={`option-${optionIndex}`}
                                >
                                  <input
                                    className="admin-input"
                                    value={option.value}
                                    placeholder="值"
                                    aria-label={`选项 ${optionIndex + 1} 的值`}
                                    onChange={(event) =>
                                      updateOption(
                                        pageIndex,
                                        questionIndex,
                                        optionIndex,
                                        { value: event.target.value },
                                      )
                                    }
                                  />
                                  <input
                                    className="admin-input"
                                    value={option.label}
                                    placeholder="显示文案"
                                    aria-label={`选项 ${optionIndex + 1} 的文案`}
                                    onChange={(event) =>
                                      updateOption(
                                        pageIndex,
                                        questionIndex,
                                        optionIndex,
                                        { label: event.target.value },
                                      )
                                    }
                                  />
                                  <button
                                    type="button"
                                    className="admin-btn admin-btn-ghost admin-btn-sm"
                                    onClick={() =>
                                      removeOption(pageIndex, questionIndex, optionIndex)
                                    }
                                    disabled={question.options.length <= 2}
                                    aria-label="删除选项"
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                </div>
                              ))}
                              <div className="admin-add-button-row">
                                <button
                                  type="button"
                                  className="admin-btn admin-btn-secondary admin-btn-sm"
                                  onClick={() => addOption(pageIndex, questionIndex)}
                                >
                                  <Plus size={13} />
                                  添加选项
                                </button>
                              </div>
                            </div>
                          ) : null}

                          {question.type === "likert" ? (
                            <div className="admin-form-row">
                              <Field
                                label="最小整数"
                                htmlFor={`questionnaire-question-min-${pageIndex}-${questionIndex}`}
                              >
                                <input
                                  id={`questionnaire-question-min-${pageIndex}-${questionIndex}`}
                                  className="admin-input"
                                  type="number"
                                  step="1"
                                  value={question.min}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      min: event.target.value,
                                    })
                                  }
                                  data-testid={`questionnaire-question-min-${pageIndex}-${questionIndex}`}
                                />
                              </Field>
                              <Field
                                label="最大整数"
                                htmlFor={`questionnaire-question-max-${pageIndex}-${questionIndex}`}
                              >
                                <input
                                  id={`questionnaire-question-max-${pageIndex}-${questionIndex}`}
                                  className="admin-input"
                                  type="number"
                                  step="1"
                                  value={question.max}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      max: event.target.value,
                                    })
                                  }
                                  data-testid={`questionnaire-question-max-${pageIndex}-${questionIndex}`}
                                />
                              </Field>
                              <Field label="最小端标签（可选）">
                                <input
                                  className="admin-input"
                                  value={question.minLabel}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      minLabel: event.target.value,
                                    })
                                  }
                                />
                              </Field>
                              <Field label="最大端标签（可选）">
                                <input
                                  className="admin-input"
                                  value={question.maxLabel}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      maxLabel: event.target.value,
                                    })
                                  }
                                />
                              </Field>
                            </div>
                          ) : null}

                          {question.type === "number" ? (
                            <div className="admin-form-row">
                              <Field label="最小值（可选）">
                                <input
                                  className="admin-input"
                                  type="number"
                                  step="any"
                                  value={question.min}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      min: event.target.value,
                                    })
                                  }
                                />
                              </Field>
                              <Field label="最大值（可选）">
                                <input
                                  className="admin-input"
                                  type="number"
                                  step="any"
                                  value={question.max}
                                  onChange={(event) =>
                                    updateQuestion(pageIndex, questionIndex, {
                                      max: event.target.value,
                                    })
                                  }
                                />
                              </Field>
                            </div>
                          ) : null}
                        </div>
                      ))}

                      <div className="admin-add-button-row">
                        <button
                          type="button"
                          className="admin-btn admin-btn-secondary admin-btn-sm"
                          onClick={() => addQuestion(pageIndex)}
                          data-testid={`questionnaire-add-question-${pageIndex}`}
                        >
                          <Plus size={14} />
                          添加题目
                        </button>
                      </div>
                    </div>
                  ))}

                  <div className="admin-add-button-row">
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={addPage}
                      data-testid="questionnaire-add-page"
                    >
                      <Plus size={15} />
                      添加页面
                    </button>
                  </div>
                </div>

                <div className="admin-sticky-side">
                  <div className="admin-editor-toolbar">
                    <h3 className="admin-section-title" style={{ marginBottom: 0 }}>
                      <Eye size={15} style={{ verticalAlign: "-2px", marginRight: "4px" }} />
                      实时预览
                    </h3>
                  </div>
                  <QuestionnairePreview draft={draft} />
                  {draftJSON.errors.length === 0 ? (
                    <div style={{ marginTop: "16px" }}>
                      <JsonDetails value={draftJSON.schema} label="查看当前 schema JSON" />
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
