// SPDX-License-Identifier: MIT
// User-flow QA round 3 (2026-10-03): the shared Button component -- see
// Button.tsx's own header comment for why this exists.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "@marketplace/Button";
describe("Button", () => {
  it("renders its label and fires onClick when not loading/disabled", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button", {
      name: "Save"
    });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
  it("loading disables the button, sets aria-busy, and shows a spinner", () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(button.querySelector("svg")).toBeInTheDocument();
  });
  it("explicit disabled also blocks the click, independent of loading", () => {
    const onClick = vi.fn();
    render(<Button disabled onClick={onClick}>Save</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });
  it("forwards data-testid and other standard button attributes", () => {
    render(<Button data-testid="my-button" type="submit">Go</Button>);
    expect(screen.getByTestId("my-button")).toHaveAttribute("type", "submit");
  });
});