import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "../app/App";
import { session } from "../api/client";
import { ToastProvider } from "../components/Toast";

export function renderApp(path: string, user?: string) {
  if (user) session.set(user);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider><App /></ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
