#!/usr/bin/env node
/**
 * The protocol driver: one JSON object in on stdin, one out on stdout.
 *
 * `docs/EXTRACTOR_PROTOCOL.md` is the contract. Exit code is zero in
 * every path short of a crash, including "I understood nothing you
 * asked for" — the orchestrator reads `skipped` to find out what
 * happened, and a non-zero exit would make it discard the specific
 * reasons worked out here in favour of a generic one.
 */

import { EXTRACTOR_ID, PROTOCOL, runRequest } from './index.js';

function emit(response) {
  process.stdout.write(JSON.stringify(response) + '\n');
}

function skippedAll(reason) {
  return {
    protocol: PROTOCOL,
    extractor: EXTRACTOR_ID,
    facts: [],
    skipped: [{ want: '*', reason, extractor: EXTRACTOR_ID }],
  };
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

async function main() {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (error) {
    emit(skippedAll(`stdin was not one JSON object: ${error.message}`));
    return;
  }

  if (request.protocol !== PROTOCOL) {
    // Refuse rather than attempt. Answering a protocol version this
    // build does not understand means answering a question it may be
    // misreading, and a wrong fact is worse than a missing one.
    emit(
      skippedAll(
        `orchestrator speaks protocol ${request.protocol}; this extractor speaks ${PROTOCOL}`
      )
    );
    return;
  }
  if (typeof request.root !== 'string' || request.root === '') {
    emit(skippedAll('the request carried no root path'));
    return;
  }

  // --client-fn NAME (repeatable): project-local wrapper functions that
  // make HTTP requests. See findClientCalls in scan.js for why this is
  // opt-in rather than inferred.
  const clientFunctions = [];
  const argv = process.argv.slice(2);
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--client-fn' && argv[index + 1]) {
      clientFunctions.push(argv[index + 1]);
      index += 1;
    }
  }

  emit(runRequest(request, { clientFunctions }));
}

main().catch((error) => {
  // Even an unexpected crash produces a well-formed response. The
  // orchestrator would otherwise see unparseable stdout and report
  // "produced output that is not one JSON object", which is true but
  // says nothing about what actually went wrong.
  emit(skippedAll(`${error.name}: ${error.message}`));
});
