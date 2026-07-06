import type { ReactNode } from "react";

export type AdvancedManagementToolsProps = {
  connectionPanel: ReactNode;
  settingsPanel: ReactNode;
  wikiWorkflowPanel: ReactNode;
};

export function AdvancedManagementTools({
  connectionPanel,
  settingsPanel,
  wikiWorkflowPanel,
}: AdvancedManagementToolsProps) {
  return (
    <div className="control-secondary-grid">
      {connectionPanel}

      {wikiWorkflowPanel}

      {settingsPanel}
    </div>
  );
}
