import { useState } from "react";

import type { QuestionnaireContextResponse } from "./apiTypes";
import {
  CONTINUE_QUESTIONNAIRE,
  QUESTIONNAIRE_DUPLICATE,
  QUESTIONNAIRE_LINK_FAILED,
} from "./flowCopy";
import { formatUnknownError, isUnauthorized } from "./apiTypes";
import { useSession } from "./session";

export function ContinueQuestionnaireButton({
  roomId,
  testId = "continue-questionnaire",
  className = "p-btn p-btn-primary",
  label = CONTINUE_QUESTIONNAIRE,
  disabled = false,
}: {
  roomId: string;
  testId?: string;
  className?: string;
  label?: string;
  disabled?: boolean;
}) {
  const session = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const openQuestionnaire = async () => {
    if (loading || disabled) return;
    setError("");
    setLoading(true);
    try {
      const context = await session.request<QuestionnaireContextResponse>(
        `/api/questionnaire/context?roomId=${encodeURIComponent(roomId)}`,
      );
      if (context.submitted) {
        setError(QUESTIONNAIRE_DUPLICATE);
        return;
      }
      if (context.url === null) {
        setError(QUESTIONNAIRE_LINK_FAILED);
        return;
      }
      window.location.href = context.url;
    } catch (error: unknown) {
      if (!isUnauthorized(error)) {
        setError(
          formatUnknownError(
            error,
            "无法继续填写问卷，请稍后重试或联系实验主试。",
          ),
        );
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className={className}
        data-testid={testId}
        disabled={loading || disabled}
        onClick={() => void openQuestionnaire()}
      >
        {loading ? "正在打开问卷…" : label}
      </button>
      {error !== "" ? (
        <span className="p-error" role="alert">
          {error}
        </span>
      ) : null}
    </>
  );
}
