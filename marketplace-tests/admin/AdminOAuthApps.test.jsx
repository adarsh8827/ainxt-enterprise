// SPDX-License-Identifier: MIT
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminOAuthApps } from "@marketplace/admin/AdminOAuthApps";
import { EcosystemApiError } from "@marketplace/lib/client/EcosystemClient";
describe("AdminOAuthApps", () => {
  it("shows the empty state, then a real created app after submitting the form", async () => {
    renderWithHost(<AdminOAuthApps />);
    await waitFor(() => expect(screen.getByTestId("oauth-apps-empty")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("oauth-app-client-id"), {
      target: {
        value: "test-client-id"
      }
    });
    fireEvent.change(screen.getByTestId("oauth-app-client-secret"), {
      target: {
        value: "test-client-secret"
      }
    });
    fireEvent.click(screen.getByTestId("oauth-app-submit"));
    await waitFor(() => expect(screen.getByTestId("oauth-app-status")).toBeInTheDocument());
    expect(screen.getByTestId("oauth-apps-list")).toBeInTheDocument();
    const row = screen.getByTestId("oauth-app-row");
    expect(row).toHaveTextContent("GitHub");
    expect(row).toHaveTextContent("test-client-id");
    // The secret is never rendered anywhere on this screen once saved.
    expect(screen.queryByText("test-client-secret")).not.toBeInTheDocument();
  });
  it("shows the real redirect URI for the selected provider so an admin can copy it into the provider console", async () => {
    renderWithHost(<AdminOAuthApps />);
    await waitFor(() => expect(screen.getByTestId("oauth-app-redirect-uri")).toBeInTheDocument());
    expect(screen.getByTestId("oauth-app-redirect-uri").textContent).toMatch(/\/ainxt\/v1\/api\/connectors\/oauth\/callback\/github$/);
    fireEvent.change(screen.getByTestId("oauth-app-provider"), {
      target: {
        value: "slack"
      }
    });
    expect(screen.getByTestId("oauth-app-redirect-uri").textContent).toMatch(/\/ainxt\/v1\/api\/connectors\/oauth\/callback\/slack$/);
  });
  it("shows a real error instead of crashing when the backend rejects the app", async () => {
    const {
      client
    } = renderWithHost(<AdminOAuthApps />);
    await waitFor(() => expect(screen.getByTestId("oauth-apps-empty")).toBeInTheDocument());
    vi.spyOn(client, "createOAuthApp").mockRejectedValueOnce(new EcosystemApiError("FORBIDDEN", "You don't have permission to manage OAuth apps.", false));
    fireEvent.change(screen.getByTestId("oauth-app-client-id"), {
      target: {
        value: "x"
      }
    });
    fireEvent.change(screen.getByTestId("oauth-app-client-secret"), {
      target: {
        value: "y"
      }
    });
    fireEvent.click(screen.getByTestId("oauth-app-submit"));
    await waitFor(() => expect(screen.getByTestId("oauth-app-error")).toHaveTextContent(/permission/));
    expect(screen.getByTestId("oauth-apps-empty")).toBeInTheDocument();
  });
  it("removes an app from the list after Remove is clicked", async () => {
    renderWithHost(<AdminOAuthApps />);
    await waitFor(() => expect(screen.getByTestId("oauth-apps-empty")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("oauth-app-client-id"), {
      target: {
        value: "id-to-delete"
      }
    });
    fireEvent.change(screen.getByTestId("oauth-app-client-secret"), {
      target: {
        value: "secret"
      }
    });
    fireEvent.click(screen.getByTestId("oauth-app-submit"));
    await waitFor(() => expect(screen.getByTestId("oauth-app-row")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("oauth-app-delete"));
    // User-flow QA round 8 (2026-10-03, audit finding): Remove now confirms
    // first -- deleteOAuthApp must NOT fire until that's confirmed.
    expect(await screen.findByTestId("confirm-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("oauth-app-row")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(screen.getByTestId("oauth-apps-empty")).toBeInTheDocument());
    expect(screen.queryByTestId("oauth-app-row")).not.toBeInTheDocument();
  });

  it("cancelling the Remove confirmation keeps the app configured", async () => {
    renderWithHost(<AdminOAuthApps />);
    await waitFor(() => expect(screen.getByTestId("oauth-apps-empty")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("oauth-app-client-id"), { target: { value: "id-to-keep" } });
    fireEvent.change(screen.getByTestId("oauth-app-client-secret"), { target: { value: "secret" } });
    fireEvent.click(screen.getByTestId("oauth-app-submit"));
    await waitFor(() => expect(screen.getByTestId("oauth-app-row")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("oauth-app-delete"));
    fireEvent.click(await screen.findByTestId("confirm-dialog-cancel"));
    expect(screen.getByTestId("oauth-app-row")).toBeInTheDocument();
  });
});