import type { ComponentProps, ReactNode } from "react";
import { Live2DModelPanel } from "../live2d/Live2DModelPanel";

export type AdvancedManagementToolsProps = ComponentProps<typeof Live2DModelPanel> & {
  connectionPanel: ReactNode;
  settingsPanel: ReactNode;
  wikiWorkflowPanel: ReactNode;
};

export function AdvancedManagementTools({
  connectionPanel,
  settingsPanel,
  wikiWorkflowPanel,
  ...live2dModelProps
}: AdvancedManagementToolsProps) {
  return (
    <div className="control-secondary-grid">
      <Live2DModelPanel {...live2dModelProps} />

      {connectionPanel}

      {wikiWorkflowPanel}

      {settingsPanel}
    </div>
  );
}
