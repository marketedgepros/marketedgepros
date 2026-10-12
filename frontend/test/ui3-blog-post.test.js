import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(
  new URL("../src/pages/BlogPost.jsx", import.meta.url),
  "utf8",
);

test("reading progress handles documents without scrollable height and stays bounded", () => {
  assert.match(source, /const scrollableHeight = documentHeight - windowHeight/);
  assert.match(source, /scrollableHeight > 0[\s\S]*\? \(scrollTop \/ scrollableHeight\) \* 100[\s\S]*: 0/);
  assert.match(source, /Math\.min\(Math\.max\(progress, 0\), 100\)/);
});

test("article tags are visibly informational rather than pretending to be controls", () => {
  const tagClass = source.match(/className="([^"]+)"\n\s*>\n\s*#\{tag\}/)?.[1] ?? "";
  assert.ok(tagClass, "tag styling should remain present");
  assert.doesNotMatch(tagClass, /cursor-pointer|hover:/);
});

test("social share buttons expose distinct accessible names and remain explicit buttons", () => {
  for (const label of ["Share on Facebook", "Share on X/Twitter", "Share on LinkedIn"]) {
    assert.ok(source.includes(`aria-label="${label}"`), `${label} should be accessible`);
  }
  assert.equal((source.match(/type="button"/g) ?? []).length >= 3, true);
});
