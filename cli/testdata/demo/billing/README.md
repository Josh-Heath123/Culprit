A deliberately faulty component, for the demo repository.

Two real faults are planted here, one per acceptance criterion Phase 29
could not otherwise demonstrate end to end:

  * `invoices.total_cents` is declared on the ORM model and is never
    created by the migration chain. The code will select a column the
    database does not have.
  * `BILLING_WEBHOOK_SECRET` is read by `config.py` and is absent from
    `.env.example`. A fresh deploy will come up missing it.

The other two components of the demo (`orders-api`, `web`) are the Phase
28 extraction fixtures, reused unmodified. This one exists because those
two are *correct*, and a corpus of correct fixtures cannot show that the
tool finds anything.

Do not "fix" the faults.
