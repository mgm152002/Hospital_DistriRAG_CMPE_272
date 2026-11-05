import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Skeleton } from "../components/States";
import ReaderPage from "../pages/ReaderPage";
import SearchPage from "../pages/SearchPage";
import { PersonaPicker } from "./PersonaPicker";
import { canUse, homeFor, SessionProvider, useSession, type Area } from "./session";
import { Forbidden, Shell } from "./Shell";

const DesignPage = lazy(() => import("../pages/DesignPage"));
const Assistant = lazy(() => import("../pages/AssistantPage"));
const Library = lazy(() => import("../pages/LibraryPage"));
const Upload = lazy(() => import("../pages/UploadWizard"));
const Version = lazy(() => import("../pages/VersionPage"));
const Compliance = lazy(() => import("../pages/CompliancePage"));
const Ops = lazy(() => import("../pages/OpsPage"));
const Settings = lazy(() => import("../pages/SettingsPage"));
const Login = lazy(() => import("../pages/LoginPage"));
const Admin = lazy(() => import("../pages/AdminPage"));
const Profile = lazy(() => import("../pages/ProfilePage"));

function Guard({ area, children }: { area: Area; children: React.ReactNode }) {
  const { me } = useSession();
  return canUse(me, area) ? <>{children}</> : <Forbidden />;
}

function Routed() {
  const { me, loading, config } = useSession();
  if (loading) return <div className="p-10"><Skeleton /></div>;
  if (!me) return config?.mode === "header" ? <PersonaPicker />
    : <Suspense fallback={<Skeleton />}><Login /></Suspense>;
  return (
    <Shell>
      <Suspense fallback={<Skeleton />}>
        <Routes>
          <Route path="/" element={<Navigate to={homeFor(me)} replace />} />
          <Route path="/search" element={<Guard area="search"><SearchPage /></Guard>} />
          <Route path="/assistant" element={<Guard area="assistant"><Assistant /></Guard>} />
          <Route path="/documents/:documentId" element={<ReaderPage />} />
          <Route path="/library" element={<Guard area="library"><Library /></Guard>} />
          <Route path="/library/new" element={<Guard area="library"><Upload /></Guard>} />
          <Route path="/library/:documentId/new-version" element={<Guard area="library"><Upload /></Guard>} />
          <Route path="/versions/:versionId" element={<Guard area="operations"><Version /></Guard>} />
          <Route path="/compliance/*" element={<Guard area="compliance"><Compliance /></Guard>} />
          <Route path="/ops" element={<Guard area="operations"><Ops /></Guard>} />
          <Route path="/settings" element={<Guard area="settings"><Settings /></Guard>} />
          <Route path="/admin/*" element={<Guard area="admin"><Admin /></Guard>} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/login" element={<Navigate to={homeFor(me)} replace />} />
          <Route path="/register" element={<Navigate to={homeFor(me)} replace />} />
          <Route path="/design" element={<DesignPage />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </Suspense>
    </Shell>
  );
}

export function App() {
  return <SessionProvider><Routed /></SessionProvider>;
}
