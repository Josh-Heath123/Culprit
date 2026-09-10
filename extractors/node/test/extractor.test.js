/**
 * The Node extractor, against the fixture corpus, plus the shared
 * conformance fixtures.
 *
 * The conformance tests matter most. This package carries a *third*
 * implementation of subject construction (see src/subjects.js for why),
 * and the only thing keeping three implementations honest is that all
 * three read the same two files out of shared/tests/. A case is added
 * there, never here.
 *
 * `node --test`, no framework. The package's whole promise is that it
 * installs into somebody else's project with one pure-JS dependency;
 * bringing in a test runner would undercut that in its own repository.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { runRequest, SUPPORTED_WANTS } from '../src/index.js';
import { findClientCalls, findRouteDefinitions, parseSource } from '../src/scan.js';
import {
  buildSubject,
  canonicalComponent,
  canonicalIdentifier,
  canonicalMethod,
  canonicalPath,
  SubjectError,
} from '../src/subjects.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SHARED = join(HERE, '..', '..', '..', 'shared', 'tests');
const FIXTURES = join(HERE, '..', '..', '..', 'cli', 'testdata', 'fixtures');

function readFixture(name) {
  // A hard failure, never a skip: these files are the single source of
  // truth for all three implementations, and skipping past a missing one
  // would let this implementation drift silently — the exact failure the
  // fixture exists to prevent.
  return JSON.parse(readFileSync(join(SHARED, name), 'utf8'));
}

// --- conformance, against the same fixtures Python and Go read ---------

test('canonicalisation matches the shared conformance fixture', () => {
  const fixture = readFixture('canonical_conformance.json');
  const groups = [
    ['path', canonicalPath, fixture.path],
    ['method', canonicalMethod, fixture.method],
    ['component', canonicalComponent, fixture.component],
    ['identifier', canonicalIdentifier, fixture.identifier],
  ];
  assert.ok(fixture.path.length > 0, 'the fixture has no path cases');

  for (const [label, fn, cases] of groups) {
    for (const testCase of cases) {
      assert.equal(
        fn(testCase.source),
        testCase.canonical,
        `${label}(${JSON.stringify(testCase.source)}) — ${testCase.convention}`
      );
      // Idempotence, for every case: a subject gets rebuilt from a
      // parsed one, so a non-idempotent normaliser would make a
      // round-tripped subject stop matching the original.
      assert.equal(
        fn(fn(testCase.source)),
        testCase.canonical,
        `${label} is not idempotent for ${JSON.stringify(testCase.source)}`
      );
    }
  }
});

test('subject construction matches the shared conformance fixture', () => {
  const fixture = readFixture('subject_conformance.json');
  const kinds = new Set(['component', 'http', 'dep']);
  let checked = 0;
  for (const testCase of fixture.build) {
    if (!kinds.has(testCase.kind)) continue; // not this extractor's business
    assert.equal(
      buildSubject(testCase.kind, testCase.parts),
      testCase.subject,
      testCase.why ?? testCase.subject
    );
    checked += 1;
  }
  assert.ok(checked >= 5, `only ${checked} cases applied; the fixture may have moved`);
});

test('subject build errors match the shared conformance fixture', () => {
  const fixture = readFixture('subject_conformance.json');
  const kinds = new Set(['component', 'http', 'dep']);
  for (const testCase of fixture.build_errors) {
    if (!kinds.has(testCase.kind)) continue;
    assert.throws(
      () => buildSubject(testCase.kind, testCase.parts),
      SubjectError,
      testCase.why ?? JSON.stringify(testCase.parts)
    );
  }
});

test('a scoped package round-trips as a dep subject', () => {
  // The `/` in `@babel/parser` used to be refused, which silently
  // dropped most of a real project's dependencies.
  assert.equal(
    buildSubject('dep', { component: 'web', dependency: '@babel/parser' }),
    'dep:web/@babel/parser'
  );
});

// --- client call sites --------------------------------------------------

test('fetch and axios call sites are found', () => {
  const source = `
    fetch('/api/v1/orders');
    fetch('/api/v1/orders', { method: 'POST' });
    axios.get('/healthz');
    api.delete('/api/v1/orders/42');
  `;
  const calls = findClientCalls(parseSource(source));
  assert.deepEqual(
    calls.map((call) => `${call.method} ${call.path}`).sort(),
    ['DELETE /api/v1/orders/42', 'GET /api/v1/orders', 'GET /healthz', 'POST /api/v1/orders']
  );
});

test('a template path becomes a parameter, not a truncated literal', () => {
  // `/users/${id}` is not a call to `/users`, and reporting it as one
  // would invent a route that does not exist.
  const calls = findClientCalls(parseSource('fetch(`/users/${id}/reset`);'));
  assert.equal(calls.length, 1);
  assert.equal(canonicalPath(calls[0].path), '/users/{}/reset');
});

test('a trailing interpolation after a segment is skipped, not glued on', () => {
  // `` `/model/graph${query}` `` where query is `?symptom=x`. Gluing the
  // placeholder on produced `/model/graph{}`, a subject no server route
  // can ever match — a permanent false positive on a correct repository.
  // Culprit found this one in its own frontend.
  const calls = findClientCalls(parseSource('fetch(`/model/graph${query}`);'));
  assert.deepEqual(calls, [], 'an unresolvable path was reported as a call');
});

test('a literal query string ends the path', () => {
  const calls = findClientCalls(parseSource('fetch(`/model/graph?symptom=${s}`);'));
  assert.equal(calls.length, 1);
  assert.equal(canonicalPath(calls[0].path), '/model/graph');
});

test('an interpolation after a slash is still a path segment', () => {
  // The rule above must not swallow the common case, which is most call
  // sites in a React codebase.
  const calls = findClientCalls(parseSource('fetch(`/users/${id}`);'));
  assert.equal(calls.length, 1);
  assert.equal(canonicalPath(calls[0].path), '/users/{}');
});

test('a fully dynamic path is skipped rather than guessed', () => {
  const calls = findClientCalls(parseSource('fetch(url); fetch(BASE + path);'));
  assert.deepEqual(calls, []);
});

test('an absolute URL to somebody else\'s system is not a route of ours', () => {
  const calls = findClientCalls(parseSource("fetch('https://api.stripe.com/v1/charges');"));
  assert.deepEqual(calls, []);
});

test('a project-local wrapper is found only when named', () => {
  const source = "apiRequest('/api/v1/orders');";
  assert.deepEqual(findClientCalls(parseSource(source)), []);
  const named = findClientCalls(parseSource(source), ['apiRequest']);
  assert.equal(named.length, 1);
  assert.equal(named[0].path, '/api/v1/orders');
});

// --- route definitions --------------------------------------------------

test('route definitions need a handler, so a client call is not mistaken for one', () => {
  // `api.get('/x')` is a request; `api.get('/x', handler)` is a route.
  // Without the arity check both look identical, and every client call
  // would be reported as a route the component serves.
  const routes = findRouteDefinitions(parseSource("api.get('/x'); app.get('/y', handler);"));
  assert.deepEqual(
    routes.map((route) => `${route.method} ${route.path}`),
    ['GET /y']
  );
});

test('app.all is reported once under *, not expanded into eight routes', () => {
  const routes = findRouteDefinitions(parseSource("app.all('/health', handler);"));
  assert.deepEqual(routes.map((route) => route.method), ['*']);
});

// --- whole requests -----------------------------------------------------

test('an unsupported want is skipped with a reason', () => {
  const response = runRequest({
    protocol: 1,
    root: join(FIXTURES, 'react-web'),
    want: ['db_schema'],
    component: 'web',
  });
  assert.deepEqual(response.facts, []);
  assert.equal(response.skipped.length, 1);
  assert.match(response.skipped[0].reason, /does not extract/);
});

test('the react-web fixture yields client calls and dependencies', () => {
  const response = runRequest(
    {
      protocol: 1,
      root: join(FIXTURES, 'react-web'),
      want: ['client_calls', 'dependencies'],
      component: 'web',
    },
    { clientFunctions: ['apiRequest'] }
  );
  const subjects = new Set(response.facts.map((fact) => fact.subject));
  assert.ok(subjects.has('http:web/GET /api/v1/orders'), 'the list call was not found');
  assert.ok(subjects.has('http:web/GET /api/v1/orders/{}'), 'the templated call was not found');
  assert.ok(subjects.has('http:web/GET /healthz'), 'the bare fetch was not found');
  // The call to a route the API does not serve — the divergence Phase 29
  // exists to find. It must be captured, not filtered out for looking odd.
  assert.ok(
    subjects.has('http:web/GET /api/v2/orders/search'),
    'the v2 call was not captured'
  );
  assert.ok(subjects.has('dep:web/@tanstack/react-query'), 'scoped packages were dropped');
});

test('the express fixture, written by somebody else, yields its routes', () => {
  // expressjs/express's own examples/route-separation at 4.21.2,
  // unmodified: four modules registering routes against one `app`.
  const response = runRequest({
    protocol: 1,
    root: join(FIXTURES, 'third-party', 'express-route-separation'),
    want: ['http_routes'],
    component: 'express-app',
  });
  const subjects = new Set(response.facts.map((fact) => fact.subject));
  assert.ok(subjects.has('http:express-app/GET /'), `got ${[...subjects].join(', ')}`);
  assert.ok(subjects.has('http:express-app/GET /users'));
  // `app.get('/user/:id', ...)` — the `:id` canonicalises to `{}`, the
  // same form a FastAPI `/user/{id}` reduces to. That equality is the
  // entire reason canonicalisation exists.
  assert.ok(subjects.has('http:express-app/GET /user/{}'));
  assert.ok(subjects.has('http:express-app/PUT /user/{}/edit'));
  // `app.all('/user/:id/*', ...)` — a route registered for every method
  // stays one fact under `*` rather than becoming eight.
  assert.ok(subjects.has('http:express-app/* /user/{}/{}'));
  assert.ok(
    response.facts.every((fact) => fact.provenance.confidence_rank === 60),
    'static extraction from framework code is rank 60 (§2.4)'
  );
});

test('an empty directory reports why it yielded nothing', () => {
  const response = runRequest({
    protocol: 1,
    root: join(FIXTURES, 'third-party', 'express-route-separation', 'views'),
    want: ['client_calls'],
    component: 'nothing',
  });
  assert.deepEqual(response.facts, []);
  assert.equal(response.skipped.length, 1);
  assert.ok(response.skipped[0].reason.length > 0);
});

test('every supported want is one the orchestrator knows about', () => {
  // A want this extractor answers under a name the Go side never sends
  // is a silently dead code path.
  const orchestratorWants = new Set([
    'http_routes',
    'db_schema',
    'config_keys',
    'client_calls',
    'test_assertions',
    'dependencies',
  ]);
  for (const want of SUPPORTED_WANTS) {
    assert.ok(orchestratorWants.has(want), `${want} is not a want the orchestrator sends`);
  }
});

test('no fact carries a config value', () => {
  // This extractor emits no config facts at all, which is the strongest
  // possible form of the guarantee — asserted rather than assumed, so
  // that adding a config reader later without a ValueShape fails here.
  const response = runRequest({
    protocol: 1,
    root: join(FIXTURES, 'react-web'),
    want: [...SUPPORTED_WANTS],
    component: 'web',
  });
  for (const fact of response.facts) {
    assert.ok(
      !fact.subject.startsWith('config:'),
      `${fact.subject} is a config fact; it must carry a value_shape, not a value`
    );
  }
});

test('a component name that cannot form a subject is reported, not swallowed', () => {
  // The component name is constant for a whole run, so a name carrying a
  // forbidden token drops *every* call site — and the report used to read
  // "scanned N files, 0 calls", indistinguishable from a project that
  // makes none. That silent gap is what this package's own honesty rule
  // forbids.
  const response = runRequest(
    {
      protocol: 1,
      root: join(FIXTURES, 'react-web'),
      want: ['client_calls'],
      // `->` is the connection separator: a subject built with it would
      // parse back as something else, so buildSubject refuses it.
      component: 'web->api',
    },
    { clientFunctions: ['apiRequest'] }
  );
  assert.deepEqual(response.facts, [], 'facts were emitted under a bad subject');
  assert.equal(response.skipped.length, 1);
  assert.match(response.skipped[0].reason, /could not be given a subject URI/);
  assert.equal(response.skipped[0].want, 'client_calls');
});

test('a good component name still yields calls, so the test above is not vacuous', () => {
  const response = runRequest(
    {
      protocol: 1,
      root: join(FIXTURES, 'react-web'),
      want: ['client_calls'],
      component: 'web',
    },
    { clientFunctions: ['apiRequest'] }
  );
  assert.ok(response.facts.length > 0);
  assert.deepEqual(response.skipped, []);
});
