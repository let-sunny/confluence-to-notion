/** Read Confluence REST settings from the environment (ADR-00M / CONTRIBUTING). */

export function readConfluenceBaseUrl(): string {
  const raw = process.env.CONFLUENCE_BASE_URL?.trim();
  if (raw !== undefined && raw.length > 0) {
    return raw.endsWith("/") ? raw.slice(0, -1) : raw;
  }
  return "https://cwiki.apache.org/confluence";
}

export function readConfluenceAuth(): { email: string; token: string } {
  const email = process.env.CONFLUENCE_EMAIL?.trim();
  const token = process.env.CONFLUENCE_API_TOKEN?.trim() ?? process.env.CONFLUENCE_TOKEN?.trim();
  if (email === undefined || email.length === 0) {
    throw new Error("Missing CONFLUENCE_EMAIL (required for Confluence basic auth).");
  }
  if (token === undefined || token.length === 0) {
    throw new Error("Missing CONFLUENCE_API_TOKEN (or legacy CONFLUENCE_TOKEN).");
  }
  return { email, token };
}
