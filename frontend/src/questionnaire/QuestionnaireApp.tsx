import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import type { QuestionnaireContext } from "../shared/types";
import "./questionnaire-extra.css";
import QuestionField from "./QuestionField";
import {
  finishJatosAndRedirect,
  getJatos,
  readJatosResultIds,
  readQueryParam,
  resolvePlatformBase,
  submitJatosResultData,
  waitForJatos,
  type JatosApi,
} from "./jatos";
import {
  PlatformError,
  completeQuestionnaire,
  fetchQuestionnaireContext,
  saveQuestionnaireDraft,
} from "./platform";
import {
  countAnswered,
  flattenQuestions,
  hasAnswer,
  isProtectedQuestionType,
  normalizeAnswers,
  omitProtectedAnswers,
  sanitizeAnswers,
  validateAnswers,
} from "./questions";
import { isIdentityDocumentAnswer } from "./validation";

type Screen = "loading" | "error" | "form" | "done";
type SaveState = "idle" | "pending" | "saving" | "saved" | "error";

interface LoadedQuestionnaire {
  jatos: JatosApi;
  base: string;
  token: string;
  pid: string | null;
  context: QuestionnaireContext;
}

interface DoneState {
  reason: "completed" | "submitted";
  redirectUrl: string;
}

const SAVE_STATUS_TEXT: Record<SaveState, string> = {
  idle: "",
  pending: "草稿未保存",
  saving: "正在保存草稿…",
  saved: "草稿已保存",
  error: "草稿未保存",
};

const SUBMIT_ERROR_HEADLINE = "后测问卷提交失败，请重试或联系实验工作人员。";

export default function QuestionnaireApp() {
  const [screen, setScreen] = useState<Screen>("loading");
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState<LoadedQuestionnaire | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [draftRestored, setDraftRestored] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitIssue, setSubmitIssue] = useState<string | null>(null);
  const [done, setDone] = useState<DoneState | null>(null);

  const runIdRef = useRef(0);
  const dirtyRef = useRef(false);
  const saveSequenceRef = useRef(0);
  const draftTimerRef = useRef<number | null>(null);
  const submitLockRef = useRef(false);

  const initialize = useCallback(async () => {
    const runId = ++runIdRef.current;
    setScreen("loading");
    setLoadError("");
    setLoaded(null);
    setAnswers({});
    setDraftRestored(false);
    setSaveState("idle");
    setSubmitAttempted(false);
    setSubmitIssue(null);
    setDone(null);
    dirtyRef.current = false;
    try {
      const jatos = getJatos();
      if (!jatos) {
        throw new Error("无法识别问卷链接，请从实验平台重新打开问卷。");
      }
      const ready = await waitForJatos(jatos);
      if (runId !== runIdRef.current) return;
      const base = resolvePlatformBase(ready);
      const token = readQueryParam(ready, "rt");
      if (!token) {
        throw new Error(
          "问卷链接不完整，请从实验平台重新打开问卷；如仍无法打开，请联系实验工作人员。",
        );
      }
      const pid = readQueryParam(ready, "pid");
      const context = await fetchQuestionnaireContext(base, token);
      if (runId !== runIdRef.current) return;
      if (pid !== null && pid !== context.analysisCode) {
        throw new Error(
          "问卷链接与当前账号不匹配，请从实验平台重新打开问卷。",
        );
      }
      setLoaded({ jatos: ready, base, token, pid, context });
      if (context.completed) {
        setDone({ reason: "completed", redirectUrl: context.redirectUrl });
        setScreen("done");
        return;
      }
      const restored = sanitizeAnswers(
        context.questionnaire.schema,
        context.draftAnswers ?? context.existingAnswers,
        context.questionnaire.protectedQuestionIds,
      );
      setAnswers(restored);
      setDraftRestored(Object.keys(restored).length > 0);
      setScreen("form");
    } catch (error) {
      if (runId !== runIdRef.current) return;
      setLoadError(messageOf(error));
      setScreen("error");
    }
  }, []);

  useEffect(() => {
    void initialize();
    return () => {
      runIdRef.current += 1;
    };
  }, [initialize]);

  useEffect(() => {
    return () => {
      saveSequenceRef.current += 1;
      if (draftTimerRef.current !== null) {
        window.clearTimeout(draftTimerRef.current);
        draftTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (screen !== "form" || !loaded || !dirtyRef.current) return;
    const sequence = ++saveSequenceRef.current;
    setSaveState("pending");
    draftTimerRef.current = window.setTimeout(() => {
      draftTimerRef.current = null;
      setSaveState("saving");
      const questionnaire = loaded.context.questionnaire;
      const draftAnswers = omitProtectedAnswers(
        flattenQuestions(questionnaire.schema),
        answers,
        questionnaire.protectedQuestionIds,
      );
      void saveQuestionnaireDraft(loaded.base, loaded.token, draftAnswers)
        .then(() => {
          if (sequence === saveSequenceRef.current) setSaveState("saved");
        })
        .catch(() => {
          if (sequence === saveSequenceRef.current) setSaveState("error");
        });
    }, 800);
    return () => {
      if (draftTimerRef.current !== null) {
        window.clearTimeout(draftTimerRef.current);
        draftTimerRef.current = null;
      }
    };
  }, [answers, loaded, screen]);

  const schema = loaded?.context.questionnaire.schema ?? null;
  const questions = useMemo(() => (schema ? flattenQuestions(schema) : []), [schema]);
  const hasProtectedQuestions = useMemo(
    () => questions.some((question) => isProtectedQuestionType(question.type)),
    [questions],
  );
  const answeredCount = useMemo(() => countAnswered(questions, answers), [questions, answers]);
  const validationErrors = useMemo(
    () => (submitAttempted ? validateAnswers(questions, answers) : {}),
    [submitAttempted, questions, answers],
  );
  const hasValidationErrors = Object.keys(validationErrors).length > 0;
  const progressPercent =
    questions.length === 0 ? 0 : Math.round((answeredCount / questions.length) * 100);

  function setAnswer(questionId: string, value: unknown) {
    dirtyRef.current = true;
    setAnswers((previous) => {
      if (!hasAnswer(value) && !isIdentityDocumentAnswer(value)) {
        if (!(questionId in previous)) return previous;
        const next = { ...previous };
        delete next[questionId];
        return next;
      }
      return { ...previous, [questionId]: value };
    });
  }

  function focusQuestion(questionId: string) {
    const index = questions.findIndex((question) => question.id === questionId);
    if (index < 0) return;
    const target =
      document.getElementById(`q-question-${index}-input`) ??
      document.getElementById(`q-question-${index}-option-0`);
    if (target instanceof HTMLElement) target.focus();
  }

  async function submitAnswers(): Promise<void> {
    if (!loaded || screen !== "form" || submitLockRef.current) return;
    setSubmitAttempted(true);
    setSubmitIssue(null);
    const normalizedAnswers = normalizeAnswers(questions, answers);
    const errors = validateAnswers(questions, normalizedAnswers);
    const firstInvalid = questions.find((question) => errors[question.id] !== undefined);
    if (firstInvalid) {
      focusQuestion(firstInvalid.id);
      return;
    }
    submitLockRef.current = true;
    setSubmitting(true);
    try {
      const jatos = loaded.jatos;
      await submitJatosResultData(jatos, {
        answers: normalizedAnswers,
        questionnaireVersionId: loaded.context.questionnaire.versionId,
        contentHash: loaded.context.questionnaire.contentHash,
        analysisCode: loaded.context.analysisCode,
      });
      const ids = readJatosResultIds(jatos);
      if (!ids) {
        throw new Error(
          "问卷提交信息不完整，请重试；如仍失败，请联系实验工作人员。",
        );
      }
      const result = await completeQuestionnaire(loaded.base, {
        token: loaded.token,
        answers: normalizedAnswers,
        jatosWorkerId: ids.workerId,
        jatosStudyResultId: ids.studyResultId,
        jatosComponentResultId: ids.componentResultId,
      });
      const redirectUrl = result.redirectUrl || loaded.context.redirectUrl;
      setDone({ reason: "submitted", redirectUrl });
      setScreen("done");
      finishJatosAndRedirect(jatos, redirectUrl);
    } catch (error) {
      if (error instanceof PlatformError && error.status === 409) {
        const refreshed = await fetchCompletedContext(loaded);
        if (refreshed) {
          setDone({ reason: "completed", redirectUrl: refreshed.redirectUrl });
          setScreen("done");
          return;
        }
      }
      setSubmitIssue(
        error instanceof PlatformError && error.status === 400
          ? "答案未通过校验，请检查必填项后重试。"
          : messageOf(error),
      );
    } finally {
      setSubmitting(false);
      submitLockRef.current = false;
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitAnswers();
  }

  function returnToPlatform() {
    if (!loaded || !done) return;
    finishJatosAndRedirect(loaded.jatos, done.redirectUrl);
  }

  if (screen === "loading") {
    return (
      <main className="q-page">
        <div className="q-container">
          <div className="q-loading" role="status">
            正在加载问卷…
          </div>
        </div>
      </main>
    );
  }

  if (screen === "error") {
    return (
      <main className="q-page">
        <div className="q-container">
          <div className="q-card q-error-panel">
            <h1 className="q-title">无法打开问卷</h1>
            <div className="q-error" role="alert">
              {loadError}
            </div>
            <p className="q-description">请检查网络后重试。如果问题持续出现，请联系实验工作人员。</p>
            <div className="q-error-actions">
              <button
                type="button"
                className="q-btn q-btn-primary"
                data-testid="questionnaire-retry"
                onClick={() => void initialize()}
              >
                重试
              </button>
            </div>
          </div>
        </div>
      </main>
    );
  }

  if (screen === "done" && done) {
    return (
      <main className="q-page">
        <div className="q-container">
          <div className="q-done" data-testid="questionnaire-done">
            <h1 className="q-done-title">问卷已完成</h1>
            <p className="q-done-text">
              {done.reason === "submitted"
                ? "你的答案已提交，可以返回实验平台查看完成情况。"
                : "你已经提交过后测问卷，可以返回实验平台查看完成情况。"}
            </p>
            {done.redirectUrl ? (
              <button type="button" className="q-btn q-btn-primary" onClick={returnToPlatform}>
                返回平台
              </button>
            ) : (
              <p className="q-done-text">请联系实验工作人员返回实验平台。</p>
            )}
          </div>
        </div>
      </main>
    );
  }

  if (!loaded || !schema) {
    return (
      <main className="q-page">
        <div className="q-container">
          <div className="q-loading" role="status">
            正在加载问卷…
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="q-page">
      <div className="q-container">
        <header className="q-header">
          <h1 className="q-title" data-testid="questionnaire-title">
            {schema.title}
          </h1>
          {schema.description ? <p className="q-description">{schema.description}</p> : null}
        </header>

        <div
          className="q-progress"
          role="progressbar"
          aria-label="答题进度"
          aria-valuemin={0}
          aria-valuemax={questions.length}
          aria-valuenow={answeredCount}
          aria-valuetext={`已作答 ${answeredCount} / ${questions.length} 题`}
        >
          <div className="q-progress-bar">
            <div className="q-progress-fill" style={{ width: `${progressPercent}%` }} />
          </div>
          <span>{`已作答 ${answeredCount} / ${questions.length} 题`}</span>
        </div>

        <div className="q-save-row" aria-live="polite">
          {saveState !== "idle" ? (
            <span className={`q-save-state${saveState === "error" ? " q-save-state-error" : ""}`}>
              {SAVE_STATUS_TEXT[saveState]}
            </span>
          ) : null}
        </div>

        {draftRestored ? <p className="q-note">已恢复上次未提交的答案。</p> : null}

        {hasProtectedQuestions ? (
          <p className="q-note">
            受保护的身份信息仅用于报酬发放，不会保存为问卷草稿；刷新页面后需要重新填写。
          </p>
        ) : null}

        {submitIssue ? (
          <div className="q-error" role="alert">
            <p className="q-error-message">{SUBMIT_ERROR_HEADLINE}</p>
            <p className="q-error-detail">{submitIssue}</p>
            <div className="q-error-actions">
              <button
                type="button"
                className="q-btn q-btn-secondary"
                data-testid="questionnaire-retry"
                disabled={submitting}
                onClick={() => void submitAnswers()}
              >
                重试
              </button>
            </div>
          </div>
        ) : null}

        {submitAttempted && hasValidationErrors ? (
          <div className="q-error" role="alert">
            请检查并完成标有错误的题目后再提交。
          </div>
        ) : null}

        <form className="q-form" onSubmit={handleSubmit} noValidate aria-busy={submitting}>
          {questions.map((question, index) => (
            <QuestionField
              key={question.id}
              question={question}
              index={index}
              value={answers[question.id]}
              error={validationErrors[question.id]}
              disabled={submitting}
              onChange={(value) => setAnswer(question.id, value)}
            />
          ))}

          <div className="q-submit-row">
            <button
              type="submit"
              className="q-btn q-btn-primary"
              data-testid="questionnaire-submit"
              disabled={submitting}
            >
              {submitting ? "正在提交…" : "提交问卷"}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}

async function fetchCompletedContext(current: LoadedQuestionnaire): Promise<QuestionnaireContext | null> {
  try {
    const context = await fetchQuestionnaireContext(current.base, current.token);
    return context.completed ? context : null;
  } catch {
    return null;
  }
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message !== "") return error.message;
  return "发生未知错误，请重试。";
}
