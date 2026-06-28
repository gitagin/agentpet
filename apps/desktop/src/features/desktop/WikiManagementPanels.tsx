import type { ComponentProps } from "react";
import { WikiBrowserPanel } from "../wiki/WikiBrowserPanel";
import { WikiWorkflowPanel } from "../wiki/WikiWorkflowPanel";

export type WikiManagementPanelsProps = {
  browser: ComponentProps<typeof WikiBrowserPanel>;
  workflow: ComponentProps<typeof WikiWorkflowPanel>;
};

export function WikiManagementPanels({ browser, workflow }: WikiManagementPanelsProps) {
  return (
    <>
      <WikiWorkflowPanel {...workflow} />
      <WikiBrowserPanel {...browser} />
    </>
  );
}
