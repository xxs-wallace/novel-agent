import { useQuery } from "@tanstack/react-query";
import { FileText, PenLine } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getArtifactTree, getArtifactView } from "../../api/artifacts";
import type { ArtifactSurface, ArtifactTreeNode } from "../../api/types";
import { ArtifactDetail } from "./ArtifactDetail";
import { ArtifactTree } from "./ArtifactTree";

interface ResultExplorerProps {
  selectedTaskId: string;
}

export function ResultExplorer({ selectedTaskId }: ResultExplorerProps) {
  const [surface, setSurface] = useState<ArtifactSurface>("close-read");
  const [selectedNode, setSelectedNode] = useState<ArtifactTreeNode | null>(null);

  const treeQuery = useQuery({
    queryKey: ["artifact-tree", selectedTaskId, surface],
    queryFn: () => getArtifactTree(selectedTaskId, surface),
    enabled: Boolean(selectedTaskId)
  });

  const nodes = treeQuery.data ?? [];
  const firstNode = useMemo(() => firstSelectableNode(nodes), [nodes]);

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedNode(null);
      return;
    }
    if (!selectedNode || selectedNode.surface !== surface || !containsNode(nodes, selectedNode.id)) {
      setSelectedNode(firstNode);
    }
  }, [firstNode, nodes, selectedNode, selectedTaskId, surface]);

  const detailQuery = useQuery({
    queryKey: ["artifact-view", selectedNode?.id],
    queryFn: () => getArtifactView(selectedNode!.id),
    enabled: Boolean(selectedNode?.id)
  });

  return (
    <div className="result-explorer">
      <div className="pane-title-row">
        <div>
          <h2>结果</h2>
          <p>{selectedTaskId ? "阅读 / Writer" : "请选择任务"}</p>
        </div>
      </div>
      <div className="result-tabs" role="tablist" aria-label="结果类型">
        <button
          type="button"
          role="tab"
          aria-selected={surface === "close-read"}
          className={surface === "close-read" ? "active" : ""}
          onClick={() => setSurface("close-read")}
        >
          <FileText size={16} aria-hidden="true" />
          阅读
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={surface === "writer"}
          className={surface === "writer" ? "active" : ""}
          onClick={() => setSurface("writer")}
        >
          <PenLine size={16} aria-hidden="true" />
          Writer
        </button>
      </div>
      {!selectedTaskId ? (
        <div className="empty-state">选择任务后会加载目录树。</div>
      ) : (
        <div className="result-grid">
          <div className="tree-shell">
            {treeQuery.isLoading ? <div className="empty-state">正在加载目录树...</div> : null}
            {treeQuery.error ? <div className="form-error">{String(treeQuery.error)}</div> : null}
            <ArtifactTree nodes={nodes} selectedId={selectedNode?.id} onSelect={setSelectedNode} />
          </div>
          <div className="detail-shell">
            <ArtifactDetail view={detailQuery.data} isLoading={detailQuery.isLoading} />
          </div>
        </div>
      )}
    </div>
  );
}

function firstSelectableNode(nodes: ArtifactTreeNode[]): ArtifactTreeNode | null {
  for (const node of nodes) {
    return node;
  }
  return null;
}

function containsNode(nodes: ArtifactTreeNode[], id: string): boolean {
  for (const node of nodes) {
    if (node.id === id || containsNode(node.children, id)) {
      return true;
    }
  }
  return false;
}
