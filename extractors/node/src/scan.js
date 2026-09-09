/**
 * Static extraction from JavaScript and TypeScript sources.
 *
 * `@babel/parser`, not tree-sitter. The plan's field 11 names
 * tree-sitter, and it is the right tool in the abstract — but its npm
 * binding is a native module built through node-gyp, which turns
 * `npm install culprit-extract-node` into a compiler toolchain
 * requirement in exactly the projects that are least likely to have one.
 * `web-tree-sitter` avoids that by being WASM, but then the grammars
 * have to be compiled and shipped as `.wasm` blobs, which is a build
 * pipeline of its own.
 *
 * `@babel/parser` is pure JavaScript, ~2 MB, has no native step, and
 * parses `.js`, `.jsx`, `.ts` and `.tsx` with one call. It is also what
 * most of these projects already have in their tree. Recorded as a plan
 * correction in docs/HANDOFF.md §5 rather than made quietly.
 *
 * Nothing here imports or executes the project's code. That is the
 * difference from the Python extractor and the reason these facts carry
 * lower ranks: a route registered in a loop, behind a variable path, or
 * by a dynamically-required router is not seen. Fewer facts, never wrong
 * ones.
 */

import { readFileSync } from 'node:fs';
import { parse } from '@babel/parser';

import { buildSubject } from './subjects.js';

const PARSER_OPTIONS = {
  sourceType: 'unambiguous',
  errorRecovery: true,
  plugins: [
    'typescript',
    'jsx',
    'decorators-legacy',
    'classProperties',
    'topLevelAwait',
    'importAssertions',
  ],
};

const HTTP_METHODS = new Set(['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'all']);

/** Objects an HTTP client call is conventionally made on. */
const CLIENT_OBJECTS = new Set(['axios', 'api', 'http', 'client', 'request', 'apiClient']);

/** Names an Express/Fastify/Koa app or router is conventionally bound to. */
const ROUTER_OBJECTS = new Set(['app', 'router', 'server', 'fastify', 'api']);

export function parseSource(source) {
  return parse(source, PARSER_OPTIONS);
}

/**
 * Walks a Babel AST, calling `visit` for every node.
 *
 * A hand-rolled walk rather than `@babel/traverse`, which is a much
 * larger dependency that exists to *transform* trees. Reading one is a
 * dozen lines.
 */
function walk(node, visit) {
  if (node === null || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit);
    return;
  }
  if (typeof node.type === 'string') visit(node);
  for (const key of Object.keys(node)) {
    if (key === 'loc' || key === 'leadingComments' || key === 'trailingComments') continue;
    walk(node[key], visit);
  }
}

/** A string literal, or a template literal with no interpolation. */
function literalString(node) {
  if (!node) return null;
  if (node.type === 'StringLiteral') return node.value;
  if (node.type === 'TemplateLiteral' && node.expressions.length === 0) {
    return node.quasis.map((quasi) => quasi.value.cooked).join('');
  }
  // A template *with* interpolation is handled by templateRoute below,
  // not here: this function's contract is "a literal string or nothing".
  return null;
}

/**
 * `` `/users/${id}/reset-password` `` -> `/users/:x/reset-password`.
 *
 * Every interpolation becomes a parameter placeholder, which
 * `canonicalPath` then normalises to `{}` — the same form a FastAPI
 * `/users/{id}` and an Express `/users/:id` reduce to. Dropping these
 * would lose most of the call sites in a typical React codebase, since
 * any call with an id in the path is a template.
 *
 * The one thing it must not do is treat the literal head as the whole
 * path: `` `/users/${id}` `` is not a call to `/users`, and reporting it
 * as one would invent a route. Hence a placeholder per expression rather
 * than a truncation.
 */
function templateRoute(node) {
  if (!node || node.type !== 'TemplateLiteral' || node.expressions.length === 0) return null;
  let path = '';
  node.quasis.forEach((quasi, index) => {
    path += quasi.value.cooked;
    if (index < node.expressions.length) path += ':x';
  });
  return path;
}

/** A literal path, or a template with its interpolations parameterised. */
function routePath(node) {
  return literalString(node) ?? templateRoute(node);
}

function lineOf(node) {
  return node?.loc?.start?.line ?? 0;
}

/**
 * Finds HTTP client call sites.
 *
 * Three shapes, all of them literal-path only:
 *   fetch('/api/v2/users')                    -> GET (or the init method)
 *   axios.get('/api/v2/users')                -> GET
 *   api.post('/orders', body)                 -> POST
 *
 * A path that does not start with `/` is skipped: `fetch(url)` and
 * `fetch('https://api.stripe.com/v1/charges')` are respectively unknown
 * and somebody else's system. The second is a real limit — an outbound
 * call to a third party is worth modelling — but it belongs to a `dep:`
 * subject rather than an `http:` one, and inventing a component name for
 * `api.stripe.com` here would produce a subject nothing else can match.
 */
export function findClientCalls(ast, extraClientFunctions = []) {
  const calls = [];
  // Project-local wrapper functions, named explicitly by the user with
  // --client-fn. Almost every real codebase funnels its HTTP through one
  // (`request('/users', {method: 'PATCH'})` is this repo's own frontend),
  // and no generic extractor can recognise it. Guessing — treating any
  // one-string-argument call as a request — would flood the report with
  // routes that do not exist, so this is opt-in and explicit. Undeclared,
  // those call sites are simply not found, and the skip reason says so.
  const wrappers = new Set(['fetch', ...extraClientFunctions]);

  walk(ast.program, (node) => {
    if (node.type !== 'CallExpression') return;
    const callee = node.callee;

    if (callee.type === 'Identifier' && wrappers.has(callee.name)) {
      const path = routePath(node.arguments[0]);
      if (path && path.startsWith('/')) {
        calls.push({ method: fetchMethod(node.arguments[1]), path, line: lineOf(node) });
      }
      return;
    }

    if (callee.type !== 'MemberExpression' || callee.computed) return;
    const property = callee.property;
    const object = callee.object;
    if (property.type !== 'Identifier' || !HTTP_METHODS.has(property.name)) return;
    if (object.type !== 'Identifier' || !CLIENT_OBJECTS.has(object.name)) return;
    const path = routePath(node.arguments[0]);
    if (path && path.startsWith('/')) {
      calls.push({ method: property.name.toUpperCase(), path, line: lineOf(node) });
    }
  });
  return calls;
}

/** Reads `{ method: 'POST' }` out of a fetch init object. */
function fetchMethod(init) {
  if (!init || init.type !== 'ObjectExpression') return 'GET';
  for (const property of init.properties) {
    if (
      property.type === 'ObjectProperty' &&
      !property.computed &&
      property.key.type === 'Identifier' &&
      property.key.name === 'method'
    ) {
      const method = literalString(property.value);
      if (method) return method.toUpperCase();
    }
  }
  return 'GET';
}

/**
 * Finds server route definitions — `app.get('/x', handler)`.
 *
 * Deliberately narrow: the object has to be one of the conventional
 * router names and the path has to be a literal. Accepting any
 * `x.get('/y')` would sweep up every client call in the same file as a
 * route definition, which is a confidently wrong fact about what a
 * component serves.
 *
 * `app.all(...)` is reported under the `*` method rather than expanded,
 * because a route registered for every method is a different claim from
 * eight separate routes.
 */
export function findRouteDefinitions(ast) {
  const routes = [];
  walk(ast.program, (node) => {
    if (node.type !== 'CallExpression') return;
    const callee = node.callee;
    if (callee.type !== 'MemberExpression' || callee.computed) return;
    if (callee.property.type !== 'Identifier' || !HTTP_METHODS.has(callee.property.name)) return;
    if (callee.object.type !== 'Identifier' || !ROUTER_OBJECTS.has(callee.object.name)) return;
    // A route definition always takes a handler after the path. A client
    // call usually does not — this is what separates `router.get('/x',
    // handler)` from `api.get('/x')` when both objects are named `api`.
    if (node.arguments.length < 2) return;
    const path = literalString(node.arguments[0]);
    if (!path || !path.startsWith('/')) return;
    const method = callee.property.name === 'all' ? '*' : callee.property.name.toUpperCase();
    routes.push({ method, path, line: lineOf(node) });
  });
  return routes;
}

/** Parses one file, returning null when it cannot be read or parsed. */
export function readAndParse(path) {
  let source;
  try {
    source = readFileSync(path, 'utf8');
  } catch {
    return null;
  }
  try {
    return parseSource(source);
  } catch {
    // A file this parser cannot read — a Vue SFC, a `.js` that is really
    // a config blob — contributes nothing. Not an error: the rest of the
    // tree is still worth reading.
    return null;
  }
}

export { buildSubject };
