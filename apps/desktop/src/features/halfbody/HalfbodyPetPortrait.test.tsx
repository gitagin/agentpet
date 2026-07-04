import { createRef } from "react";
import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HalfbodyPetPortrait } from "./HalfbodyPetPortrait";
import type { HalfbodyPetPortraitHandle } from "./HalfbodyPetPortrait";

function currentVisemeLayer(container: HTMLElement) {
  return container.querySelector(".halfbody-pet-portrait-viseme") as HTMLImageElement | null;
}

describe("HalfbodyPetPortrait", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("removes overlay layers when transparent overlay assets are missing", () => {
    const { container } = render(<HalfbodyPetPortrait />);

    const baseLayer = container.querySelector(".halfbody-pet-portrait-base");
    const blinkLayer = container.querySelector(".halfbody-pet-portrait-blink") as HTMLImageElement;
    const visemeLayer = container.querySelector(".halfbody-pet-portrait-viseme") as HTMLImageElement;

    expect(baseLayer).toBeInTheDocument();

    fireEvent.error(blinkLayer);
    fireEvent.error(visemeLayer);

    expect(container.querySelector(".halfbody-pet-portrait-base")).toBeInTheDocument();
    expect(container.querySelector(".halfbody-pet-portrait-blink")).not.toBeInTheDocument();
    expect(container.querySelector(".halfbody-pet-portrait-viseme")).not.toBeInTheDocument();
  });

  it("exposes direct viseme control and timeline-driven speech without fake mouth motion", () => {
    const portraitRef = createRef<HalfbodyPetPortraitHandle>();
    const { container } = render(<HalfbodyPetPortrait ref={portraitRef} />);

    expect(currentVisemeLayer(container)?.src).toContain("closed.png");

    act(() => {
      portraitRef.current?.setHalfbodyViseme("AI");
    });
    expect(currentVisemeLayer(container)?.src).toContain("AI.png");

    act(() => {
      portraitRef.current?.speak(null);
    });
    expect(currentVisemeLayer(container)?.src).toContain("closed.png");

    act(() => {
      portraitRef.current?.speak(null, [
        { phoneme: "m", startMs: 20, durationMs: 30 },
        { phoneme: "e", startMs: 70, durationMs: 30 },
        { phoneme: "o", startMs: 120, durationMs: 30 },
      ]);
      vi.advanceTimersByTime(20);
    });
    expect(currentVisemeLayer(container)?.src).toContain("closed.png");

    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(currentVisemeLayer(container)?.src).toContain("AI.png");

    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(currentVisemeLayer(container)?.src).toContain("O.png");

    act(() => {
      vi.advanceTimersByTime(30);
    });
    expect(currentVisemeLayer(container)?.src).toContain("closed.png");
  });
});
