// SPDX-License-Identifier: MIT
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import ConnectPromptCard from "./ConnectPromptCard.jsx";
import UsingConnectorIndicator from "./UsingConnectorIndicator.jsx";

afterEach(() => cleanup());

describe("ConnectPromptCard", () => {
  it("shows the connector name and calls onConnect when clicked", () => {
    const onConnect = vi.fn();
    render(<ConnectPromptCard connectorName="Jira" onConnect={onConnect} />);
    expect(screen.getByText(/needs access to/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("connect-prompt-connect-button"));
    expect(onConnect).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows Connecting… while connecting", () => {
    render(<ConnectPromptCard connectorName="Jira" onConnect={() => {}} connecting />);
    const button = screen.getByTestId("connect-prompt-connect-button");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Connecting…");
  });
});

describe("UsingConnectorIndicator", () => {
  it("renders the connector name", () => {
    render(<UsingConnectorIndicator connectorName="Jira" />);
    expect(screen.getByTestId("using-connector-indicator")).toHaveTextContent("Using Jira");
  });
});
