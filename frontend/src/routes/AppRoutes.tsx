import { Navigate, Route, Routes, useSearchParams } from "react-router-dom";

import { LoginScreen } from "@/components/auth/LoginScreen";
import { Dashboard } from "@/components/Dashboard";
import { useAuthToken } from "@/hooks/useAuth";

import { InvestigationList } from "./InvestigationList";
import { InvestigationView } from "./InvestigationView";
import { NotFound } from "./NotFound";
import { PostmortemEditor } from "./PostmortemEditor";
import { PostmortemList } from "./PostmortemList";
import { RequireAdmin } from "./RequireAdmin";
import { RequireAuth } from "./RequireAuth";
import { SettingsServices } from "./SettingsServices";
import { SettingsUsers } from "./SettingsUsers";

/** Only ever a same-origin relative path, never wherever `?next=`
 * literally says — react-router's own changelog is full of open-redirect
 * advisories for exactly this shape of bug (an unvalidated redirect
 * target read back out of a query string), so this is validated here
 * rather than trusted. Rejects a `next` that isn't a plain in-app path:
 * an absolute URL (`https://…`), a protocol-relative one (`//evil.com`,
 * browser-parsed the same as `https://evil.com`), or a leading backslash
 * (browsers normalize `\` to `/`, another way to smuggle the same
 * bypass). */
function safeNext(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\") || raw.includes("://")) {
    return "/";
  }
  return raw;
}

/** /login itself: if there's already a valid session, there's nothing to
 * log in for — bounce straight to `next` (or `/`) instead of showing the
 * form again. */
function LoginRoute() {
  const token = useAuthToken();
  const [searchParams] = useSearchParams();

  if (token) {
    return <Navigate to={safeNext(searchParams.get("next"))} replace />;
  }
  return <LoginScreen />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />

      <Route element={<RequireAuth />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/incidents/:incidentId" element={<Dashboard />} />
        <Route path="/incidents/:incidentId/postmortem" element={<PostmortemEditor />} />
        <Route path="/investigations" element={<InvestigationList />} />
        <Route path="/investigations/:investigationId" element={<InvestigationView />} />
        <Route path="/postmortems" element={<PostmortemList />} />
        <Route path="/postmortems/new" element={<PostmortemEditor />} />
        <Route path="/postmortems/:postmortemId" element={<PostmortemEditor />} />
        <Route element={<RequireAdmin />}>
          <Route path="/settings/services" element={<SettingsServices />} />
          <Route path="/settings/users" element={<SettingsUsers />} />
        </Route>
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
