import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  apiRequest,
  configureAuthTokenGetter,
  configureUnauthorizedHandler,
} from "./client";
import { ApiError } from "./types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiRequest", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    configureAuthTokenGetter(() => "test-access-token");
    configureUnauthorizedHandler(async () => false);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("attaches the Authorization header when a token is available", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await apiRequest("/organizations");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-access-token");
  });

  it("does not attach Authorization for an anonymous request", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await apiRequest("/auth/login", { method: "POST", body: {}, anonymous: true });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("parses the standard error envelope into an ApiError", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(404, {
        error: {
          code: "NOT_FOUND",
          message: "Organization not found.",
          correlation_id: "corr-1",
        },
      }),
    );

    await expect(apiRequest("/organizations/does-not-exist")).rejects.toMatchObject({
      code: "NOT_FOUND",
      message: "Organization not found.",
      correlationId: "corr-1",
      status: 404,
    });
  });

  it("retries once after a successful refresh on 401", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Expired." } }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    configureUnauthorizedHandler(async () => true);

    const result = await apiRequest<{ ok: boolean }>("/organizations");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry an anonymous request even on 401", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Bad login." } }),
    );
    const refreshHandler = vi.fn(async () => true);
    configureUnauthorizedHandler(refreshHandler);

    await expect(
      apiRequest("/auth/login", { method: "POST", body: {}, anonymous: true }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(refreshHandler).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("propagates the original 401 when refresh fails", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Expired." } }),
    );
    configureUnauthorizedHandler(async () => false);

    await expect(apiRequest("/organizations")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
