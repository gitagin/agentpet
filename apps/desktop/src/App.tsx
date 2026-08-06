import { AppShell } from "./AppShell";

/**
 * Stable renderer entry point.  Domain orchestration lives in AppShell so
 * bootstrap, tests, and future providers do not depend on the implementation
 * details of the window-specific views.
 */
export default function App() {
  return <AppShell />;
}
