import { Link } from "react-router-dom";

import { EmptyPanel } from "@/components/ui/states";

/** No incidents in the record. Since Phase 32 part 2 nothing opens new
 * ones — the correlation engine was retired and the tables are read-only —
 * so the copy says that rather than "Culprit is watching", which would
 * promise incidents that will never arrive. */
export function EmptyState() {
  return (
    <EmptyPanel title="No incidents in the record">
      The earlier correlation engine recorded none on this install, and it no longer runs. Diagnoses are{" "}
      <Link to="/investigations" className="text-brand underline-offset-2 hover:underline">
        investigations
      </Link>{" "}
      now.
    </EmptyPanel>
  );
}
