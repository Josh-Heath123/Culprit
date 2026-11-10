# Security: what each compromise can and cannot do

Culprit's agent runs read-only probes inside your production network, under
grants written in its own configuration file, and takes its tasks from a
control plane over an outbound connection. This is the threat model for that
arrangement (Phase 33): six things that can go wrong, and for each, what an
attacker holding it can do and what stops them.

**Every claim below that something is impossible names the test that
enforces it**, as `path::TestName`. `scripts/check_security_doc.py` fails CI
if such a claim names no test, or names one that does not exist. A claim
nobody tests is not in this file.

The parts, in one paragraph: an **agent** holds an Ed25519 key it generated
itself, and signs every request with it. It holds its **grants** in its own
configuration file; the control plane sends an **allowance** with each task,
which can only narrow them. It writes a hash-chained **audit log** locally
before it answers, and ships it to the control plane's append-only
`agent_audit_log`. The control plane is the API behind the dashboard. A
**pairing code** registers an agent once. The **project token** is CI's
credential for posting what `culprit check` and `culprit diagnose` produce.
`docs/PERMISSIONS.md` describes each in full.

## 1. A compromised control plane

Someone controls the API: they can address any task to any agent and send any
allowance with it, answer requests however they like, and read everything the
control plane stores.

They **can**: make an agent run any probe its own configuration grants, on
any target, as often as they like; withhold any grant from a task; read every
reading, investigation and audit entry ever stored; stop answering, so agents
exit.

- An allowance **cannot** add a grant the agent's own configuration does not
  give: the agent intersects the two, and ignores and records a name it does
  not hold. `cli/internal/agent/config_test.go::TestNarrowingCanWithholdAGrantButNeverAddOne`,
  `cli/cmd/culprit/agent_transport_test.go::TestAnAllowanceNamingAGrantTheConfigurationLacksIsRefusedOverTheTransport`
- A task that needs a grant the agent does not hold **cannot** make it dial
  anything: it is refused before the network is touched, and the refusal is
  recorded. `cli/cmd/culprit/agent_test.go::TestATaskNeedingAnUngrantedCapabilityIsRefusedWithoutDialling`
- It **cannot** make an agent write to anything it probes: no probe in the
  catalogue mutates, no write capability exists, and the parser refuses one.
  `cli/internal/probe/probe_test.go::TestNoProbeInTheCatalogueMutates`,
  `cli/internal/agent/config_test.go::TestTheParserRefusesWildcardsAllAndUnknownGrantsNamingTheLine`
- It **cannot** reach into the agent: nothing in the binary listens on a
  socket. `cli/cmd/culprit/listen_test.go::TestNothingInTheBinaryListens`
- It **cannot** send the agent anywhere else: the agent's transport dials
  only the configured address, follows no redirect and ignores proxy
  settings. `cli/internal/transport/transport_test.go::TestTheClientDialsOnlyItsControlPlane`,
  `cli/internal/transport/transport_test.go::TestARedirectIsNotFollowed`,
  `cli/internal/transport/transport_test.go::TestAProxyFromTheEnvironmentIsIgnored`
- It **cannot** obtain the agent's private key: pairing sends only the public
  half. `cli/cmd/culprit/agent_transport_test.go::TestPairingSendsNoPrivateKey`,
  `cli/internal/transport/transport_test.go::TestARegistrationCarriesNoPrivateKey`
- It **cannot** make an agent store or emit a secret it was allowed only to
  inspect: `config.inspect.values` reads a value in memory and never stores
  it. `cli/internal/capture/capture_test.go::TestConfigInspectValuesNeverLetsCaptureStoreAValue`,
  `cli/internal/probe/secret_source_test.go::TestConfigReadValuesDoesNotLetASecretBeInspected`
- It **cannot** quietly erase what an agent did: the agent's own log is
  hash-chained, and an edited, removed or reordered entry is caught.
  `cli/internal/agent/audit_test.go::TestAnEditedEntryIsCaught`,
  `cli/internal/agent/audit_test.go::TestADeletedEntryIsCaught`,
  `cli/internal/agent/audit_test.go::TestReorderedEntriesAreCaught`

## 2. A compromised agent

Someone controls an agent: its process, its configuration, its key.

They **can**: run any probe that agent's configuration grants, anywhere its
network reaches, without asking the control plane; claim and answer tasks
addressed to that agent; post readings and investigations as that agent;
append to that agent's audit chain.

- It **cannot** claim another agent's task, or one task twice.
  `api/tests/test_agents_api.py::test_an_agent_claims_only_its_own_tasks_and_each_once`
- It **cannot** report the result of a task that is not its own.
  `api/tests/test_agents_api.py::test_a_result_is_recorded_once_and_only_by_its_agent`
- It **cannot** post readings, or an investigation, as another agent.
  `api/tests/test_agents_api.py::test_a_reading_naming_another_agent_is_refused`,
  `api/tests/test_agents_api.py::test_an_agent_cannot_store_another_agents_readings_as_an_investigation`
- It **cannot** rewrite or delete the audit entries the control plane holds —
  no role can update or delete a row, the owner included — nor append one that
  does not extend its stored chain.
  `api/tests/test_agents_api.py::test_no_role_the_owner_included_can_rewrite_the_audit_log`,
  `api/tests/test_agents_api.py::test_an_entry_that_does_not_extend_the_stored_chain_is_refused`,
  `api/tests/test_agents_api.py::test_the_database_refuses_an_entry_that_skips_ahead`
- It **cannot** widen its own allowance, or touch any other agent: every
  agent-management route needs an admin's session.
  `api/tests/test_route_credentials.py::test_every_agent_admin_route_needs_an_admin`
- It **cannot** use a route meant for CI or for people: an agent's signature is
  accepted only on its own routes, `POST /readings` and `POST /investigations`.
  `api/tests/test_route_credentials.py::test_every_route_an_agent_calls_for_itself_is_signed`,
  `api/tests/test_route_credentials.py::test_the_project_token_works_on_exactly_the_capture_endpoints_and_investigations`
- After it is revoked, it **cannot** make another request: the very next one
  is refused. `api/tests/test_agents_api.py::test_revoking_an_agent_refuses_its_very_next_request`,
  `cli/cmd/culprit/agent_transport_test.go::TestARevokedAgentStopsOnItsNextRequest`

## 3. A leaked pairing code

Someone has a code an admin made, before it was spent.

They **can**: pair an agent of their own, once, within 15 minutes of the code
being made. It appears on the agents screen; revoke it there.

- The code **cannot** be spent twice, or after it expires.
  `api/tests/test_agents_api.py::test_a_pairing_code_works_once`,
  `api/tests/test_agents_api.py::test_an_expired_pairing_code_is_refused`
- The stored code **cannot** be read back into a usable one: only its hash
  is kept. `api/tests/test_agents_api.py::test_a_pairing_code_is_stored_hashed`
- An agent paired with it **cannot** use any grant until an admin allows it:
  a new agent's allowance is empty, and an allowance can name only what the
  agent reported. `api/tests/test_agents_api.py::test_a_new_agents_allowance_is_empty`,
  `api/tests/test_agents_api.py::test_an_allowance_beyond_what_the_agent_reports_is_refused`
- It **cannot** register a wildcard, `all`, or an unknown grant.
  `api/tests/test_agents_api.py::test_registration_refuses_a_wildcard_all_or_unknown_grant`

## 4. A leaked agent key

Someone has a copy of one agent's key file.

They **can**: sign requests as that agent until it is revoked — claim its
tasks, post readings and investigations under its name, extend its audit
chain — which is everything in section 2.

- A request signed with any other key **cannot** pass as that agent's.
  `api/tests/test_agents_api.py::test_the_wrong_key_is_refused`
- The key **cannot** be used after the agent is revoked.
  `api/tests/test_agents_api.py::test_revoking_an_agent_refuses_its_very_next_request`
- It **cannot** widen that agent's allowance or touch another agent: every
  agent-management route needs an admin's session.
  `api/tests/test_route_credentials.py::test_every_agent_admin_route_needs_an_admin`
- It **cannot** claim another agent's task, or post readings as another
  agent. `api/tests/test_agents_api.py::test_an_agent_claims_only_its_own_tasks_and_each_once`,
  `api/tests/test_agents_api.py::test_a_reading_naming_another_agent_is_refused`
- It **cannot** rewrite the audit entries already stored, or append one that
  breaks the chain. `api/tests/test_agents_api.py::test_no_role_the_owner_included_can_rewrite_the_audit_log`,
  `api/tests/test_agents_api.py::test_an_entry_that_does_not_extend_the_stored_chain_is_refused`
- The key **cannot** be read off the machine by another local user: it is
  written mode 0600 and never overwritten.
  `cli/cmd/culprit/agent_transport_test.go::TestInitWritesAKeyOnlyItsOwnerCanReadAndNeverOverwritesOne`

## 5. A leaked project token

Someone has `CULPRIT_PROJECT_TOKEN`, the credential CI posts captures with.

They **can**: post captures (facts, divergences, the system model's
captures) and investigations, which are recorded as submitted by the project
token, not by an agent.

- It **cannot** be used on any route but `POST /facts/captures`,
  `POST /divergences/captures`, `POST /captures` and `POST /investigations`.
  `api/tests/test_route_credentials.py::test_the_project_token_works_on_exactly_the_capture_endpoints_and_investigations`,
  `api/tests/test_route_credentials.py::test_the_project_token_is_only_checked_where_the_route_table_can_see_it`
- It **cannot** post readings: only an agent's signature can.
  `api/tests/test_route_credentials.py::test_post_readings_takes_an_agents_signature_only`,
  `api/tests/test_agents_api.py::test_post_readings_takes_an_agents_credential_and_nothing_else`
- It **cannot** act as an agent: claim a task, report a result, or touch an
  audit chain. `api/tests/test_route_credentials.py::test_every_route_an_agent_calls_for_itself_is_signed`
- An investigation it posts **cannot** pass as an agent's: each records who
  submitted it. `api/tests/test_agents_api.py::test_an_investigation_records_who_stored_it`

## 6. A replayed or tampered request

Someone captured an agent's signed request on the wire, or can alter one in
flight. (The agent speaks only https to its control plane; plain http is
refused except to a loopback address, or where its configuration says
`allow_plain_http`, which it reports at every start.)

- A replayed request **cannot** be accepted twice: its nonce is spent, and
  kept for as long as the request could still be fresh.
  `api/tests/test_agents_api.py::test_a_replayed_request_is_refused`,
  `api/tests/test_agents_api.py::test_a_nonce_outlives_every_moment_its_request_could_still_be_fresh`
- A request more than 300 seconds old **cannot** be accepted.
  `api/tests/test_agents_api.py::test_a_stale_request_is_refused`
- A changed body or path **cannot** pass, and the refusal does not say which
  check failed. `api/tests/test_agents_api.py::test_a_tampered_body_or_path_is_refused_and_the_answer_does_not_say_why`
- An unsigned or badly signed request **cannot** get its body parsed, or learn
  the schema from a validation error: it is refused first.
  `api/tests/test_agents_api.py::test_an_unsigned_or_badly_signed_request_is_refused_before_its_body_is_parsed`
- The agent **cannot** be pointed at a plain-http control plane by accident:
  it refuses one unless it is a loopback address or the configuration says
  `allow_plain_http`, and then it says so at every start.
  `cli/internal/agent/config_test.go::TestPlainHTTPIsRefusedExceptToLoopbackOrWithAllowPlainHTTP`,
  `cli/cmd/culprit/agent_transport_test.go::TestAllowPlainHTTPIsReportedAtEveryStart`

## What this model does not cover

- **The machine the agent runs on.** Root there owns the agent's key, its
  configuration and its audit log. The recipes in `deploy/agent/` run it as an
  unprivileged user with a read-only root filesystem; they do not defend
  against the host.
- **The control plane's own host and database.** A database superuser can
  disable the triggers that keep `agent_audit_log` append-only.
- **Probes against what an agent is allowed to reach.** A compromised control
  plane can ask an allowed probe to run repeatedly; each run is recorded, and
  the agent's grants bound what it can touch.
- **TLS itself.** The agent trusts its system's certificate authorities for
  the control plane's https certificate.
