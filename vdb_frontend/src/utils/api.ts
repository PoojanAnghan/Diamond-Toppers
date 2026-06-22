/**
 * API Utility Client
 * Handles authenticated API requests to the Django backend.
 */

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE_URL;

interface RequestOptions extends RequestInit {
  useAuth?: boolean;
}

/**
 * Gets the stored token from localStorage.
 */
export function getStoredToken(): string | null {
  if (typeof window !== "undefined") {
    return localStorage.getItem("vdb_token");
  }
  return null;
}

/**
 * Stores the token in localStorage.
 */
export function setStoredToken(token: string, username: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("vdb_token", token);
    localStorage.setItem("vdb_username", username);
  }
}

/**
 * Clears the token from localStorage.
 */
export function clearStoredToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("vdb_token");
    localStorage.removeItem("vdb_username");
  }
}

/**
 * Custom fetch wrapper that automatically appends authentication headers
 */
export async function apiFetch(endpoint: string, options: RequestOptions = {}) {
  const { useAuth = true, headers = {}, ...restOptions } = options;
  const url = `${API_BASE_URL}/api${endpoint}`;

  const requestHeaders = new Headers(headers);

  if (useAuth) {
    const token = getStoredToken();
    if (token) {
      requestHeaders.set("Authorization", `Bearer ${token}`);
    }
  }

  const response = await fetch(url, {
    ...restOptions,
    headers: requestHeaders,
  });

  if (!response.ok) {
    // Attempt to parse JSON error message
    let errorMessage = `Request failed with status ${response.status}`;
    try {
      const errorJson = await response.json();
      errorMessage = errorJson.detail || errorMessage;
    } catch {
      // ignore
    }
    throw new Error(errorMessage);
  }

  return response;
}
