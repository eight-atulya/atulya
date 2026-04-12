import { access, readFile } from "fs/promises";
import path from "path";

export const dynamic = "force-dynamic";

async function resolveBrainTemplatePath(): Promise<string> {
  const candidates = [
    path.resolve(process.cwd(), "../atulya-cortex/life/06_tools/01_templates/brain.html"),
    path.resolve(process.cwd(), "atulya-cortex/life/06_tools/01_templates/brain.html"),
  ];

  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }

  throw new Error("brain.html template not found");
}

export async function GET() {
  const templatePath = await resolveBrainTemplatePath();
  const html = await readFile(templatePath, "utf8");

  return new Response(html, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
