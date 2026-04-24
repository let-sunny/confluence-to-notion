import { describe, expect, it } from "vitest";
import { parseConfluenceUrl } from "../src/url.js";

describe("parseConfluenceUrl", () => {
  describe("happy paths", () => {
    it("parses /wiki/spaces/<SPACE>/pages/<ID>/<title>", () => {
      const result = parseConfluenceUrl(
        "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title",
      );
      expect(result).toEqual({
        kind: "page",
        spaceKey: "ENG",
        pageId: "12345",
        title: "Some-Title",
      });
    });

    it("parses /wiki/spaces/<SPACE>/pages/<ID> without a title segment", () => {
      const result = parseConfluenceUrl(
        "https://example.atlassian.net/wiki/spaces/ENG/pages/12345",
      );
      expect(result).toEqual({
        kind: "page",
        spaceKey: "ENG",
        pageId: "12345",
      });
    });

    it("parses legacy /display/<SPACE>/<Title> and URL-decodes '+' to space", () => {
      const result = parseConfluenceUrl(
        "https://cwiki.apache.org/confluence/display/KAFKA/Some+Title",
      );
      expect(result).toEqual({
        kind: "display",
        spaceKey: "KAFKA",
        title: "Some Title",
      });
    });

    it("parses percent-encoded titles in /display/", () => {
      const result = parseConfluenceUrl(
        "https://cwiki.apache.org/confluence/display/KAFKA/Some%20Title",
      );
      expect(result).toEqual({
        kind: "display",
        spaceKey: "KAFKA",
        title: "Some Title",
      });
    });

    it("parses Confluence shortlinks of the form /x/<token>", () => {
      const result = parseConfluenceUrl("https://example.atlassian.net/wiki/x/AbCdEf1");
      expect(result).toEqual({
        kind: "shortlink",
        token: "AbCdEf1",
      });
    });

    it("parses a bare numeric string as a page id", () => {
      const result = parseConfluenceUrl("12345");
      expect(result).toEqual({
        kind: "pageId",
        pageId: "12345",
      });
    });

    it("strips query strings and fragments before matching path segments", () => {
      const result = parseConfluenceUrl(
        "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title?foo=bar&baz=qux#heading-1",
      );
      expect(result).toEqual({
        kind: "page",
        spaceKey: "ENG",
        pageId: "12345",
        title: "Some-Title",
      });
    });
  });

  describe("malformed input", () => {
    it("throws a TypeError on empty string", () => {
      expect(() => parseConfluenceUrl("")).toThrow(TypeError);
    });

    it("throws a TypeError on unrecognised non-URL input", () => {
      expect(() => parseConfluenceUrl("not-a-url")).toThrow(TypeError);
    });

    it("throws a TypeError on a non-http(s) scheme", () => {
      expect(() => parseConfluenceUrl("ftp://example.com/foo")).toThrow(TypeError);
    });

    it("throws a TypeError (not URIError) on a display URL with a malformed percent-escape", () => {
      expect(() =>
        parseConfluenceUrl("https://cwiki.apache.org/confluence/display/KAFKA/Bad%E0Title"),
      ).toThrow(TypeError);
    });

    it("throws a TypeError on an http(s) URL with no recognisable Confluence shape", () => {
      expect(() => parseConfluenceUrl("https://example.atlassian.net/some/unknown/path")).toThrow(
        TypeError,
      );
    });

    it("error message names the offending input on a single line", () => {
      const offending = "https://example.atlassian.net/not/a/confluence/path";
      try {
        parseConfluenceUrl(offending);
        throw new Error("expected parseConfluenceUrl to throw");
      } catch (err) {
        expect(err).toBeInstanceOf(TypeError);
        const message = (err as TypeError).message;
        expect(message).toBe(`Unrecognised Confluence URL: ${offending}`);
        expect(message).not.toMatch(/\n/);
      }
    });

    it("error message does not leak a stack trace in .message", () => {
      try {
        parseConfluenceUrl("bogus");
      } catch (err) {
        const message = (err as TypeError).message;
        expect(message).not.toMatch(/\s at /);
        expect(message).not.toMatch(/parseConfluenceUrl/);
      }
    });
  });
});
