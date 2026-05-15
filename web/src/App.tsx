import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { WorkspaceShell } from "./components/layout/WorkspaceShell";

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 5_000
      },
      mutations: {
        retry: false
      }
    }
  });
}

export default function App() {
  const [queryClient] = useState(createAppQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <WorkspaceShell />
    </QueryClientProvider>
  );
}
