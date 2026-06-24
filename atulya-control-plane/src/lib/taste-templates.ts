export type TasteSchemaType = "openai_chat" | "qa_pair" | "custom";

export function importTemplate(schemaType: TasteSchemaType): Record<string, unknown> {
  if (schemaType === "qa_pair") {
    return {
      question: "What is the capital of France?",
      answer: "Paris is the capital of France.",
    };
  }
  if (schemaType === "custom") {
    return { example: "your structured training row" };
  }
  return {
    messages: [
      { role: "user", content: "Summarize our refund policy in one sentence." },
      {
        role: "assistant",
        content: "Refunds are available within 30 days with proof of purchase.",
      },
    ],
  };
}

export function sampleJsonl(schemaType: TasteSchemaType): string {
  const row = importTemplate(schemaType);
  return `${JSON.stringify(row)}\n`;
}

export const DEFAULT_TASTE_TAGS = ["taste:studio"];
export const MAX_IMPORT_ROWS = 500;

function nonEmptyString(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

export function validateImportPayload(
  payload: Record<string, unknown>,
  schemaType: TasteSchemaType
): string | null {
  if (schemaType === "openai_chat") {
    const messages = payload.messages;
    if (!Array.isArray(messages) || messages.length === 0) {
      return "openai_chat requires non-empty messages[]";
    }
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (!msg || typeof msg !== "object" || Array.isArray(msg)) {
        return `messages[${i}] must be an object`;
      }
      const row = msg as Record<string, unknown>;
      if (!nonEmptyString(row.role) || !nonEmptyString(row.content)) {
        return `messages[${i}] requires non-empty role and content`;
      }
    }
    return null;
  }
  if (schemaType === "qa_pair") {
    if (!nonEmptyString(payload.question) || !nonEmptyString(payload.answer)) {
      return "qa_pair requires non-empty question and answer";
    }
    return null;
  }
  if (Object.keys(payload).length === 0) return "custom payload cannot be empty";
  return null;
}

export type JsonlValidationResult =
  | { ok: true; lineCount: number }
  | { ok: false; error: string; line?: number };

export function validateJsonlImport(
  jsonl: string,
  schemaType: TasteSchemaType
): JsonlValidationResult {
  const trimmed = jsonl.trim();
  if (!trimmed) {
    return { ok: false, error: "Paste at least one JSONL line" };
  }
  const lines = trimmed.split("\n");
  let lineCount = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    lineCount += 1;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      return { ok: false, error: `Line ${i + 1}: invalid JSON`, line: i + 1 };
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: `Line ${i + 1}: each row must be a JSON object`, line: i + 1 };
    }
    const schemaErr = validateImportPayload(parsed as Record<string, unknown>, schemaType);
    if (schemaErr) {
      return { ok: false, error: `Line ${i + 1}: ${schemaErr}`, line: i + 1 };
    }
  }
  if (lineCount === 0) {
    return { ok: false, error: "No non-empty JSONL lines found" };
  }
  if (lineCount > MAX_IMPORT_ROWS) {
    return {
      ok: false,
      error: `Import exceeds maximum of ${MAX_IMPORT_ROWS} rows per request`,
      line: lineCount,
    };
  }
  return { ok: true, lineCount };
}

export function diffJson(before: unknown, after: unknown): string {
  const beforeStr = JSON.stringify(before, null, 2);
  const afterStr = JSON.stringify(after, null, 2);
  if (beforeStr === afterStr) return "(no changes)";
  return `--- before\n+++ after\n\n${beforeStr}\n\n→\n\n${afterStr}`;
}
