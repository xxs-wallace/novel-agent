import { Code2, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getArtifactTechnical } from "../../api/artifacts";

interface TechnicalDetailsDrawerProps {
  artifactId: string;
  available: boolean;
}

export function TechnicalDetailsDrawer({ artifactId, available }: TechnicalDetailsDrawerProps) {
  const [open, setOpen] = useState(false);
  const technicalQuery = useQuery({
    queryKey: ["artifact-technical", artifactId],
    queryFn: () => getArtifactTechnical(artifactId),
    enabled: open && available
  });

  if (!available) {
    return null;
  }

  return (
    <div className="technical-drawer-root">
      <button type="button" className="secondary-button" onClick={() => setOpen(true)}>
        <Code2 size={16} aria-hidden="true" />
        技术详情
      </button>
      {open ? (
        <aside className="technical-drawer" aria-label="技术详情">
          <div className="drawer-header">
            <h3>技术详情</h3>
            <button type="button" className="icon-button" aria-label="关闭技术详情" onClick={() => setOpen(false)}>
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          {technicalQuery.isLoading ? <p>加载中...</p> : null}
          {technicalQuery.error ? <p className="form-error">{String(technicalQuery.error)}</p> : null}
          {technicalQuery.data ? <pre className="technical-json">{JSON.stringify(technicalQuery.data, null, 2)}</pre> : null}
        </aside>
      ) : null}
    </div>
  );
}
