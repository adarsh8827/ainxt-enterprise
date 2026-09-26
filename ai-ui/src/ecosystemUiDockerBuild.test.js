// SPDX-License-Identifier: MIT
// Regression test for task B-5: a real `docker build -f ai-ui/Dockerfile .`
// once failed with "Rollup failed to resolve import '@heroicons/react/24/outline'
// from '.../packages/ecosystem-ui/src/components/AddMenu.tsx'".
//
// Root cause: packages/ecosystem-ui/src has no node_modules of its own in the
// production image (only source is COPY'd, matching the pre-existing @abs/
// AgentStudio pattern) -- ai-ui/node_modules is a sibling, not an ancestor,
// of /app/packages/ecosystem-ui/src there, so Rollup's normal directory
// walk-up resolution for a bare import never reaches it unless the package
// is listed in ai-ui/vite.config.js's resolve.dedupe array (which forces
// resolution through ai-ui's own node_modules instead). This bug was
// invisible on the host dev server because packages/ecosystem-ui happens to
// have its own local node_modules there from an unrelated standalone
// `npm install` -- so this test statically checks the actual failure
// condition (every bare import used by ecosystem-ui/src is deduped) rather
// than relying on that host-only coincidence, without needing to run a real
// `docker build` in the unit test suite.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../..");
const ECOSYSTEM_UI_SRC = path.join(REPO_ROOT, "packages/ecosystem-ui/src");

// Packages ecosystem-ui's own node_modules provides that are irrelevant to
// this check: dev/test-only tooling never bundled into the ai-ui production
// build (Storybook, vitest, testing-library, ecosystem-ui's own devDeps),
// and relative/self ("required" is a string literal caught by the same
// naive scan below, not an import -- filtered explicitly).
const IGNORED_BARE_IMPORTS = new Set([
  "@storybook/react-vite",
  "@testing-library/react",
  "vitest",
  "required",
]);

function listSourceFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...listSourceFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.(test|stories)\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function bareImportsIn(fileContent) {
  const found = [];
  const importRe = /\bfrom\s+["']([^"']+)["']/g;
  let m;
  while ((m = importRe.exec(fileContent)) !== null) {
    const spec = m[1];
    if (!spec.startsWith(".") && !spec.startsWith("/")) found.push(spec);
  }
  return found;
}

function packageNameOf(spec) {
  // "@scope/pkg/subpath" -> "@scope/pkg"; "pkg/subpath" -> "pkg"
  const parts = spec.split("/");
  return spec.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
}

describe("ecosystem-ui Docker build resolution (task B-5 regression)", () => {
  it("every bare import ecosystem-ui/src actually ships (excluding react, already deduped) is listed in ai-ui/vite.config.js's resolve.dedupe", () => {
    const files = listSourceFiles(ECOSYSTEM_UI_SRC);
    expect(files.length).toBeGreaterThan(0);

    const packageNames = new Set();
    for (const file of files) {
      const content = fs.readFileSync(file, "utf8");
      for (const spec of bareImportsIn(content)) {
        if (IGNORED_BARE_IMPORTS.has(spec)) continue;
        packageNames.add(packageNameOf(spec));
      }
    }

    const viteConfig = fs.readFileSync(path.join(REPO_ROOT, "ai-ui/vite.config.js"), "utf8");
    const dedupeMatch = viteConfig.match(/dedupe:\s*\[([\s\S]*?)\]/);
    expect(dedupeMatch).not.toBeNull();
    const dedupedNames = new Set(
      [...dedupeMatch[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1]),
    );

    const missing = [...packageNames].filter((name) => !dedupedNames.has(name));
    expect(missing).toEqual([]);
  });

  it("ai-ui/Dockerfile copies packages/ecosystem-ui/src into the build context", () => {
    const dockerfile = fs.readFileSync(path.join(REPO_ROOT, "ai-ui/Dockerfile"), "utf8");
    expect(dockerfile).toMatch(/COPY\s+packages\/ecosystem-ui\/src\s+\/app\/packages\/ecosystem-ui\/src/);
  });

  it("every package ecosystem-ui/src actually imports (beyond react) that Rollup must resolve through ai-ui/node_modules is a real ai-ui dependency", () => {
    const files = listSourceFiles(ECOSYSTEM_UI_SRC);
    const packageNames = new Set();
    for (const file of files) {
      const content = fs.readFileSync(file, "utf8");
      for (const spec of bareImportsIn(content)) {
        if (IGNORED_BARE_IMPORTS.has(spec) || spec === "react") continue;
        packageNames.add(packageNameOf(spec));
      }
    }

    const aiUiPackageJson = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "ai-ui/package.json"), "utf8"));
    const declared = new Set([
      ...Object.keys(aiUiPackageJson.dependencies || {}),
      ...Object.keys(aiUiPackageJson.devDependencies || {}),
      // "overrides" alone (e.g. @codemirror/state/@codemirror/language, pinned
      // here but only actually installed because @uiw/react-codemirror/
      // @codemirror/merge already pull them in transitively) still guarantees
      // the package lands in ai-ui/node_modules -- accepted here too.
      ...Object.keys(aiUiPackageJson.overrides || {}),
    ]);

    const missing = [...packageNames].filter((name) => !declared.has(name));
    expect(missing).toEqual([]);
  });
});
