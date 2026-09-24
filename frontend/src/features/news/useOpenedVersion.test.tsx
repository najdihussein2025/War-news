import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { useOpenedVersion } from "./hooks";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let seen: Array<number | undefined> = [];

const Probe = ({ isOpen, version }: { isOpen: boolean; version: number }) => {
  seen.push(useOpenedVersion(isOpen, version));
  return null;
};

const container = document.createElement("div");
const root = createRoot(container);
const render = (isOpen: boolean, version: number) =>
  act(() => {
    root.render(<Probe isOpen={isOpen} version={version} />);
  });
const latest = () => seen[seen.length - 1];

afterEach(() => {
  seen = [];
});

describe("useOpenedVersion", () => {
  it("submits the version the editor opened with, not a newer polled one", () => {
    render(false, 3);
    expect(latest()).toBe(3);

    render(true, 3);
    // A pipeline merge bumps the version while the form is open.
    render(true, 4);
    expect(latest()).toBe(3);

    // Closing releases the snapshot; the next editor picks up the new version.
    render(false, 4);
    expect(latest()).toBe(4);
    render(true, 4);
    expect(latest()).toBe(4);
  });
});
