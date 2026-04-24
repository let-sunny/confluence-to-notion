import { describe, expect, it } from "vitest";
import { slugForUrl } from "../../src/runs/index.js";

describe("slugForUrl", () => {
  it("derives cwiki-integration-page from the Apache cwiki display URL", () => {
    expect(slugForUrl("https://cwiki.apache.org/confluence/display/TEST/Integration+Page")).toBe(
      "cwiki-integration-page",
    );
  });

  it("uses pageId query when present", () => {
    expect(slugForUrl("https://example.atlassian.net/wiki/spaces/ENG/pages?pageId=12345")).toBe(
      "example-12345",
    );
  });

  it("uses the numeric pages segment when present", () => {
    expect(
      slugForUrl("https://example.atlassian.net/wiki/spaces/ENG/pages/99999/Some-Title?foo=bar"),
    ).toBe("example-99999");
  });

  it("uses the space key after /spaces/", () => {
    expect(slugForUrl("https://example.atlassian.net/wiki/spaces/ENG")).toBe("example-eng");
  });

  it("falls back to the last path segment", () => {
    expect(slugForUrl("https://host.example.com/confluence/x/AbCdEf")).toBe("host-abcdef");
  });

  it("returns only the host label when the path is empty", () => {
    expect(slugForUrl("https://solo.example.com/")).toBe("solo");
  });
});
