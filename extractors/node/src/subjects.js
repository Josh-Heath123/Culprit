/**
 * Subject URIs and canonicalisation — the third implementation.
 *
 * There are now three: `shared/culprit_model/subjects.py`,
 * `cli/internal/model/subjects.go`, and this one. That is one more than
 * §2.3 anticipated, and it is a cost worth naming rather than hiding.
 *
 * The alternative was worse. This package's whole reason to exist is
 * that it runs in the user's own npm project (D3), where the only thing
 * that can be depended on is npm packages — a Python module and a Go
 * binary are both unavailable. Emitting hand-formatted subject strings
 * instead would put the formatting in the *readers*, spread across the
 * file, which is exactly the drift the centralisation rule forbids. One
 * module that owns the format, held to the same shared fixture as the
 * other two, is the closest thing to the rule that this boundary allows.
 *
 * `test/extractor.test.js` reads `shared/tests/subject_conformance.json`
 * and `shared/tests/canonical_conformance.json` — the same two files the
 * Python and Go tests read. Add a case there, not here.
 *
 * Only the subject kinds this extractor emits are implemented (`http`,
 * `dep`, `component`), and an unknown kind throws. A partial
 * implementation that silently produced a plausible string for a kind it
 * did not really support would be worse than one that refuses.
 */

const ARROW = '->';
const ASPECT = '#';
const PLACEHOLDER = '{}';

// Parameter placeholders inside one path segment, in the four templating
// conventions this project meets. Order matters and mirrors canonical.py:
// regex groups first, so `(?P<pk>[0-9]+)` collapses before the Express
// `:id` rule sees the colon inside it.
const PARAM_PATTERNS = [
  /\{[^{}/]*\}/g, // OpenAPI / FastAPI / Starlette
  /<[^<>/]*>/g, // Flask / Django path()
  /\((?:\?P<[^>]*>)?[^()]*\)[*+?]?/g, // Django re_path, bare regex groups
  /:[A-Za-z_][A-Za-z0-9_]*/g, // Express / Rails / Sinatra
  /\*\*?/g, // catch-alls
];

export class SubjectError extends Error {}

/** Normalises a route path to `/literal/{}/literal` form. Idempotent. */
export function canonicalPath(path) {
  let value = String(path).trim();
  if (value.startsWith('^')) value = value.slice(1);
  if (value.endsWith('$')) value = value.slice(0, -1);
  if (!value.startsWith('/')) value = '/' + value;

  const segments = value
    .split('/')
    .filter((segment) => segment !== '')
    .map(canonicalSegment);
  let normalised = '/' + segments.join('/');

  // Query string and fragment are cut *after* parameter normalisation.
  // A Django re_path route legitimately contains a `?` inside
  // `(?P<pk>...)`, and cutting first turns `^orders/(?P<pk>\d+)$` into
  // `/orders/(` — a wrong answer that still looks like a path.
  for (const cut of ['?', ASPECT]) {
    const index = normalised.indexOf(cut);
    if (index >= 0) normalised = normalised.slice(0, index);
  }
  normalised = normalised.replace(/\/+$/, '');
  return normalised === '' ? '/' : normalised;
}

function canonicalSegment(segment) {
  let value = segment;
  for (const pattern of PARAM_PATTERNS) {
    value = value.replace(pattern, PLACEHOLDER);
  }
  while (value.includes(PLACEHOLDER + PLACEHOLDER)) {
    value = value.replaceAll(PLACEHOLDER + PLACEHOLDER, PLACEHOLDER);
  }
  return value;
}

export function canonicalMethod(method) {
  return String(method).trim().toUpperCase();
}

/**
 * Lower-cased and trimmed. Underscores are deliberately not folded to
 * hyphens: `order_service` and `order-service` are genuinely different
 * names, and merging them would hide a real naming divergence.
 */
export function canonicalComponent(name) {
  return String(name).trim().toLowerCase();
}

export function canonicalIdentifier(name) {
  return String(name).trim().toLowerCase();
}

const ARROW_SEPARATED = ['/', ARROW, ASPECT, ' '];
const FORBIDDEN_IN_PART = {
  name: ARROW_SEPARATED,
  component: ARROW_SEPARATED,
  // `/` is deliberately absent: a dep subject is cut on its first `/`,
  // so `dep:web/@babel/parser` round-trips exactly. Forbidding it here
  // dropped every scoped npm package.
  dependency: [ARROW, ASPECT, ' '],
  aspect: ['/', ASPECT, ' '],
};

const REQUIRED = {
  component: ['name'],
  http: ['component', 'method', 'path'],
  dep: ['component', 'dependency'],
};

const OPTIONAL = {
  component: [],
  http: ['aspect'],
  dep: [],
};

/**
 * Constructs a canonical subject URI. The only place in this package
 * that formats one.
 */
export function buildSubject(kind, parts) {
  const required = REQUIRED[kind];
  if (!required) {
    throw new SubjectError(
      `culprit-extract-node does not build ${kind} subjects (it emits component, http and dep)`
    );
  }
  const allowed = new Set([...required, ...OPTIONAL[kind]]);
  const unexpected = Object.keys(parts).filter((name) => !allowed.has(name));
  if (unexpected.length) {
    throw new SubjectError(`${kind}: unexpected part(s) ${unexpected.sort().join(', ')}`);
  }
  const missing = required.filter((name) => !String(parts[name] ?? '').trim());
  if (missing.length) {
    throw new SubjectError(`${kind}: missing required part(s) ${missing.sort().join(', ')}`);
  }
  // A part containing one of its own separators is rejected rather than
  // embedded: it would produce a subject that parses back as something
  // else, which is a silent wrong answer rather than an error.
  for (const [name, value] of Object.entries(parts)) {
    const candidate = String(value).trim();
    const offending = (FORBIDDEN_IN_PART[name] ?? []).filter((token) =>
      candidate.includes(token)
    );
    if (offending.length) {
      throw new SubjectError(
        `${kind}: part ${name}=${JSON.stringify(value)} contains subject separator(s) ` +
          `${offending.sort().join(', ')} — it would parse back as something else`
      );
    }
  }

  switch (kind) {
    case 'component':
      return `component:${canonicalComponent(parts.name)}`;
    case 'http': {
      const base =
        `http:${canonicalComponent(parts.component)}/` +
        `${canonicalMethod(parts.method)} ${canonicalPath(parts.path)}`;
      const aspect = String(parts.aspect ?? '').trim();
      return aspect ? `${base}${ASPECT}${aspect}` : base;
    }
    case 'dep':
      return `dep:${canonicalComponent(parts.component)}/${canonicalComponent(parts.dependency)}`;
    default:
      throw new SubjectError(`unreachable subject kind ${kind}`);
  }
}
