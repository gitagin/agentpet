import { useAppShellRuntime } from "./AppShellRuntimeContext";
import { ControlRouteView } from "./ControlRouteView";
import { FeatureRoutesView } from "./FeatureRoutesView";
import { PetRouteView } from "./PetRouteView";

export function AppShellView() {
  const { app } = useAppShellRuntime();
  const mode = app.routing.windowMode;
  if (mode === "pet") {
    return <PetRouteView />;
  }
  if (mode !== "control" && mode !== "stage") {
    return <FeatureRoutesView />;
  }
  return <ControlRouteView />;
}
