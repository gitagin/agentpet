import { Bot } from "lucide-react";
import { Panel } from "../../components/layout";
import { getLive2DAssetStatusText } from "../../components/Live2DStage";
import type { Live2DAssetInfo, Live2DModelOption } from "../../services/live2dRuntime";

type Live2DModelPanelProps = {
  models: Live2DModelOption[];
  selectedModelId: string;
  asset: Live2DAssetInfo;
  onSelectModel: (modelId: string) => void;
};

export function Live2DModelPanel({
  models,
  selectedModelId,
  asset,
  onSelectModel,
}: Live2DModelPanelProps) {
  return (
    <Panel id="live2d-panel" icon={<Bot size={18} />} title="桌宠形象">
      <section className="stack" aria-label="Live2D 模型选择">
        <div className="section-heading">
          <strong>当前陪伴形象</strong>
          <span>切换后会立即影响桌宠窗口加载的 Cubism 模型。</span>
        </div>
        <label>
          <span>选择模型</span>
          <select
            value={selectedModelId}
            onChange={(event) => onSelectModel(event.target.value)}
          >
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </select>
        </label>
        <dl className="details single">
          <div>
            <dt>模型清单</dt>
            <dd>{asset.manifestPath}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{getLive2DAssetStatusText(asset).title}</dd>
          </div>
        </dl>
      </section>
    </Panel>
  );
}
