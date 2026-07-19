"use client";
import styles from "../app/page.module.css";

const NUMERIC = /(int|float|double|decimal|numeric|real|bigint|hugeint)/i;
const TEMPORAL = /(date|time|timestamp)/i;
// Identifier/position columns — aggregating them is meaningless ("total page").
const ID_LIKE = /^(id|.*_id|index|idx|page|paragraph_index|row|rownum|no|num)$/i;
// Long-form text columns, produced by the PDF/DOCX text fallback.
const TEXT_COL = /^(text|content|body|paragraph)$/i;

/** Build a few concrete starter questions from the dataset's own columns. */
function buildSuggestions(dataset) {
  const tables = dataset?.tables || [];
  const table = tables[0];
  if (!table) return [];

  const cols = table.columns || dataset?.schema?.[table.name] || [];

  // Documents ingested as text (no real tables) need document-style prompts,
  // not aggregation prompts.
  const isTextDoc =
    /document_text/i.test(table.name) || cols.some((c) => TEXT_COL.test(c.name));
  if (isTextDoc) {
    return [
      "Summarize this document.",
      "What are the main topics covered?",
      "List the key facts or figures mentioned.",
    ];
  }

  const usable = cols.filter((c) => !ID_LIKE.test(c.name));
  const numeric = usable.filter((c) => NUMERIC.test(c.type || ""));
  const temporal = usable.filter((c) => TEMPORAL.test(c.type || ""));
  const categorical = usable.filter(
    (c) => !NUMERIC.test(c.type || "") && !TEMPORAL.test(c.type || ""),
  );

  const out = ["Summarize this dataset and point out anything notable."];

  if (numeric[0] && categorical[0]) {
    out.push(
      `What is total ${numeric[0].name} by ${categorical[0].name}? Show a bar chart.`,
    );
  } else if (numeric[0]) {
    out.push(`What is the distribution of ${numeric[0].name}? Show a histogram.`);
  }

  if (temporal[0] && numeric[0]) {
    out.push(`Plot ${numeric[0].name} over ${temporal[0].name}.`);
  } else if (categorical[0]) {
    out.push(`How many rows are there per ${categorical[0].name}?`);
  }

  if (numeric.length >= 2) {
    out.push(
      `Is there a relationship between ${numeric[0].name} and ${numeric[1].name}?`,
    );
  }

  return out.slice(0, 4);
}

export default function SuggestedQuestions({ dataset, onPick, disabled }) {
  const suggestions = buildSuggestions(dataset);
  if (suggestions.length === 0) return null;

  return (
    <div className={styles.suggestWrap}>
      <div className={styles.suggestTitle}>Try asking</div>
      <div className={styles.suggestList}>
        {suggestions.map((q) => (
          <button
            key={q}
            className={styles.suggestChip}
            onClick={() => onPick(q)}
            disabled={disabled}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
