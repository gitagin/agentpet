import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

vi.mock("@xyflow/react", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  const h = React.createElement;
  return {
    Background: () => h("div", { className: "react-flow__background" }),
    Controls: () => h("div", { className: "react-flow__controls" }),
    Handle: () => h("span", { className: "memory-node-handle" }),
    MiniMap: () => h("div", { className: "react-flow__minimap" }),
    Position: { Top: "top", Bottom: "bottom" },
    ReactFlow: ({ nodes, edges, nodeTypes, onNodeClick, children, className }: any) =>
      h(
        "div",
        { className: `react-flow ${className || ""}` },
        h(
          "div",
          { className: "react-flow__edges" },
          edges.map((edge: any) =>
            h(
              "svg",
              { key: edge.id, className: `react-flow__edge ${edge.className || ""}` },
              h("path", { className: "react-flow__edge-path" }),
            ),
          ),
        ),
        h(
          "div",
          { className: "react-flow__nodes" },
          nodes.map((node: any) => {
            const NodeComponent = nodeTypes?.[node.type];
            return h(
              "div",
              {
                key: node.id,
                className: "react-flow__node",
                role: node.ariaRole || "group",
                onClick: (event: MouseEvent) => onNodeClick?.(event, node),
              },
              NodeComponent ? h(NodeComponent, { id: node.id, data: node.data, selected: false }) : null,
            );
          }),
        ),
        children,
      ),
    useEdgesState: (initialEdges: any[]) => [initialEdges, vi.fn(), vi.fn()],
    useNodesState: (initialNodes: any[]) => [initialNodes, vi.fn(), vi.fn()],
  };
});

class TestResizeObserver implements ResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

Object.defineProperty(window, "ResizeObserver", {
  configurable: true,
  writable: true,
  value: TestResizeObserver,
});

Object.defineProperty(window, "devicePixelRatio", {
  configurable: true,
  writable: true,
  value: 1,
});

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

window.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => {
  return window.setTimeout(() => callback(performance.now()), 0);
});

window.cancelAnimationFrame = vi.fn((handle: number) => {
  window.clearTimeout(handle);
});

HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as HTMLCanvasElement["getContext"];
HTMLCanvasElement.prototype.getBoundingClientRect = vi.fn(() => ({
  x: 0,
  y: 0,
  width: 320,
  height: 480,
  top: 0,
  right: 320,
  bottom: 480,
  left: 0,
  toJSON: () => ({}),
}));
