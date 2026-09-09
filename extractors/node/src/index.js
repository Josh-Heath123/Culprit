/**
 * The extraction itself: walk the tree, build facts, report the gaps.
 *
 * Every function here returns `{ facts, skipped }` and throws nothing.
 * `docs/EXTRACTOR_PROTOCOL.md`'s honesty rule is the whole design: an
 * extractor that cannot answer says so with a reason and exits zero.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

import { buildSubject, SubjectError } from './subjects.js';
import { findClientCalls, findRouteDefinitions, readAndParse } from './scan.js';

export const EXTRACTOR_VERSION = '0.1.0';
export const EXTRACTOR_ID = `culprit-extract-node@${EXTRACTOR_VERSION}`;
export const PROTOCOL = 1;

/** §2.4's ranks. */
export const RANK = {
  COMMITTED_SPEC: 80,
  STATIC_FRAMEWORK_CODE: 60,
  STATIC_CLIENT_CALL_SITES: 40,
};

export const SUPPORTED_WANTS = new Set(['client_calls', 'http_routes', 'dependencies']);

/**
 * Directories never walked. Third-party code defines and calls its own
 * routes constantly, and attributing them to the user's component would
 * be a confidently wrong fact — the worst kind this extractor can make.
 */
const SKIP_DIRS = new Set([
  'node_modules',
  '.git',
  'dist',
  'build',
  '.next',
  'coverage',
  '.turbo',
  '.cache',
  'out',
  '__pycache__',
  '.venv',
]);

const SOURCE_EXTENSIONS = ['.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts'];

/** Same bound and same reason as the Go side's maxScanDepth. */
const MAX_DEPTH = 8;

/** Every source file under root, in a stable lexical order. */
export function sourceFiles(root, depth = 0) {
  if (depth > MAX_DEPTH) return [];
  let entries;
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return [];
  }
  const found = [];
  for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : 1))) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name) || entry.name.startsWith('.')) continue;
      found.push(...sourceFiles(path, depth + 1));
    } else if (SOURCE_EXTENSIONS.some((extension) => entry.name.endsWith(extension))) {
      if (entry.name.endsWith('.d.ts')) continue; // declarations, not behaviour
      found.push(path);
    }
  }
  return found;
}

function provenance({ sourceKind, artefact, locator, rank }) {
  return {
    source_kind: sourceKind,
    extractor: EXTRACTOR_ID,
    artefact: artefact ?? null,
    locator: locator ?? null,
    confidence_rank: rank,
  };
}

function fact(context, subject, predicate, value, prov) {
  return {
    plane: 'INTENT',
    subject,
    predicate,
    value,
    environment: null,
    provenance: prov,
    captured_at: context.capturedAt,
    capture_id: context.captureId,
  };
}

function forwardSlash(root, path) {
  return relative(root, path).split(sep).join('/');
}

/**
 * Client call sites (rank 40 — the lowest static rank in §2.4).
 *
 * The subject names the *caller's* component, not the callee's, because
 * this extractor has no way to know whose route `/api/v2/users` is. The
 * orchestrator retargets these using `extract.components.<name>.calls_to`
 * from culprit.yaml when it is declared — see
 * `cli/internal/extract/orchestrator.go`. Undeclared, the fact is still
 * a truthful inventory line ("web calls GET /api/v2/users"); it simply
 * has nothing to be compared against yet.
 */
export function extractClientCalls(root, context, clientFunctions = []) {
  const facts = [];
  const refused = [];
  let scanned = 0;
  for (const path of sourceFiles(root)) {
    const ast = readAndParse(path);
    if (!ast) continue;
    scanned += 1;
    const artefact = forwardSlash(root, path);
    for (const call of findClientCalls(ast, clientFunctions)) {
      let subject;
      try {
        subject = buildSubject('http', {
          component: context.component,
          method: call.method,
          path: call.path,
        });
      } catch (error) {
        // Recorded, not swallowed. The component name is constant for a
        // whole run, so a name carrying a forbidden token drops *every*
        // call site and the report reads "scanned 47 files, 0 calls" —
        // indistinguishable from a project that makes none. That is the
        // silent gap this package's own honesty rule forbids.
        if (error instanceof SubjectError) {
          refused.push(error.message);
          continue;
        }
        throw error;
      }
      facts.push(
        fact(
          context,
          subject,
          'calls',
          { path: call.path, method: call.method },
          provenance({
            sourceKind: 'static',
            artefact,
            locator: `L${call.line}`,
            rank: RANK.STATIC_CLIENT_CALL_SITES,
          })
        )
      );
    }
  }
  if (refused.length > 0) {
    return {
      facts,
      skipped: [
        {
          want: 'client_calls',
          reason:
            `${refused.length} call site(s) could not be given a subject URI: ` +
            `${refused[0]}`,
          extractor: EXTRACTOR_ID,
        },
      ],
    };
  }
  if (facts.length === 0) {
    return {
      facts,
      skipped: [
        {
          want: 'client_calls',
          reason:
            scanned === 0
              ? 'no JavaScript or TypeScript source found under this root'
              : `no fetch/axios call with a literal path found in ${scanned} source file(s). ` +
                `If this project funnels HTTP through a wrapper function, name it with ` +
                `--client-fn <name>.`,
          extractor: EXTRACTOR_ID,
        },
      ],
    };
  }
  return { facts, skipped: [] };
}

/** Server route definitions (rank 60 — static extraction from framework code). */
export function extractRoutes(root, context) {
  const facts = [];
  let scanned = 0;
  for (const path of sourceFiles(root)) {
    const ast = readAndParse(path);
    if (!ast) continue;
    scanned += 1;
    const artefact = forwardSlash(root, path);
    for (const route of findRouteDefinitions(ast)) {
      let subject;
      try {
        subject = buildSubject('http', {
          component: context.component,
          method: route.method,
          path: route.path,
        });
      } catch (error) {
        if (error instanceof SubjectError) continue;
        throw error;
      }
      facts.push(
        fact(
          context,
          subject,
          'exists',
          { path: route.path, method: route.method },
          provenance({
            sourceKind: 'static',
            artefact,
            locator: `L${route.line}`,
            rank: RANK.STATIC_FRAMEWORK_CODE,
          })
        )
      );
    }
  }
  if (facts.length === 0) {
    return {
      facts,
      skipped: [
        {
          want: 'http_routes',
          reason:
            `no app.get/router.post-style route definition with a literal path found ` +
            `in ${scanned} source file(s). This extractor is static — a route ` +
            `registered dynamically is not visible to it.`,
          extractor: EXTRACTOR_ID,
        },
      ],
    };
  }
  return { facts, skipped: [] };
}

/** Declared dependency versions from package.json (rank 80). */
export function extractDependencies(root, context) {
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  } catch (error) {
    return {
      facts: [],
      skipped: [
        {
          want: 'dependencies',
          reason: `package.json could not be read: ${error.message}`,
          extractor: EXTRACTOR_ID,
        },
      ],
    };
  }
  const merged = { ...(manifest.devDependencies ?? {}), ...(manifest.dependencies ?? {}) };
  const facts = [];
  for (const name of Object.keys(merged).sort()) {
    let subject;
    try {
      subject = buildSubject('dep', { component: context.component, dependency: name });
    } catch (error) {
      // A scoped package (`@babel/parser`) contains a `/`, which used to
      // be refused here. It is not: a dep subject is cut on its *first*
      // `/`, so `dep:web/@babel/parser` round-trips exactly, and the ban
      // was silently dropping most of a real project's dependencies
      // (found in Phase 28 against this repo's own frontend). What is
      // still refused is a name carrying `->`, `#` or a space.
      if (error instanceof SubjectError) continue;
      throw error;
    }
    facts.push(
      fact(
        context,
        subject,
        'version',
        merged[name],
        provenance({
          sourceKind: 'spec',
          artefact: 'package.json',
          locator: null,
          rank: RANK.COMMITTED_SPEC,
        })
      )
    );
  }
  return { facts, skipped: [] };
}

/** Runs a whole request. Never throws. */
export function runRequest(request, options = {}) {
  const root = request.root;
  const context = {
    component: request.component || 'unknown',
    captureId: '00000000-0000-5000-8000-000000000000',
    capturedAt: new Date().toISOString(),
  };

  const wants = request.want && request.want.length ? request.want : [...SUPPORTED_WANTS];
  const facts = [];
  const skipped = [];

  for (const want of wants) {
    if (!SUPPORTED_WANTS.has(want)) {
      skipped.push({
        want,
        reason: `${EXTRACTOR_ID} does not extract ${want}`,
        extractor: EXTRACTOR_ID,
      });
      continue;
    }
    let result;
    try {
      if (want === 'client_calls')
        result = extractClientCalls(root, context, options.clientFunctions ?? []);
      else if (want === 'http_routes') result = extractRoutes(root, context);
      else result = extractDependencies(root, context);
    } catch (error) {
      // The honesty rule: never fail the run. A crash in one want
      // becomes a reported gap, and the others still run.
      skipped.push({
        want,
        reason: `${error.name}: ${error.message}`,
        extractor: EXTRACTOR_ID,
      });
      continue;
    }
    facts.push(...result.facts);
    skipped.push(...result.skipped);
  }

  // Sorted: the orchestrator sorts too, but an extractor whose own
  // output is stable is one whose golden file is readable.
  facts.sort((a, b) =>
    a.subject === b.subject
      ? a.predicate < b.predicate
        ? -1
        : 1
      : a.subject < b.subject
        ? -1
        : 1
  );

  return { protocol: PROTOCOL, extractor: EXTRACTOR_ID, facts, skipped };
}

export function statOrNull(path) {
  try {
    return statSync(path);
  } catch {
    return null;
  }
}
