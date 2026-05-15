import { FormEvent, useState } from "react";

interface ScopedRevisionComposerProps {
  disabled?: boolean;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown> | void;
}

export function ScopedRevisionComposer({ disabled = false, onSubmit }: ScopedRevisionComposerProps) {
  const [scope, setScope] = useState("当前选中产物");
  const [feedback, setFeedback] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!feedback.trim()) {
      return;
    }
    void onSubmit({ scope, feedback: feedback.trim() });
    setFeedback("");
  }

  return (
    <form className="scoped-revision-composer" onSubmit={handleSubmit}>
      <select value={scope} onChange={(event) => setScope(event.target.value)} aria-label="修改范围">
        <option>当前选中产物</option>
        <option>本章草稿</option>
        <option>本批剧情大纲</option>
        <option>人物百科条目</option>
      </select>
      <textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={2} placeholder="局部修改反馈" />
      <button type="submit" className="secondary-button" disabled={disabled || !feedback.trim()}>
        按反馈修改
      </button>
    </form>
  );
}
