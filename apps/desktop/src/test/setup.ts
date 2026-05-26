import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

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
