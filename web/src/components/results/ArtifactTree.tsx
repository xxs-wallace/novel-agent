import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ArtifactTreeNode } from "../../api/types";

interface ArtifactTreeProps {
  nodes: ArtifactTreeNode[];
  selectedId?: string;
  onSelect: (node: ArtifactTreeNode) => void;
}

export function ArtifactTree({ nodes, selectedId, onSelect }: ArtifactTreeProps) {
  const defaultExpanded = useMemo(() => collectExpandableIds(nodes), [nodes]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    setExpanded(defaultExpanded);
  }, [defaultExpanded]);

  function toggle(nodeId: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }

  if (!nodes.length) {
    return <div className="empty-state">还没有可浏览的产物。</div>;
  }

  return (
    <div className="artifact-tree" role="tree" aria-label="产物目录树">
      {nodes.map((node) => (
        <TreeNode key={node.id} node={node} depth={0} selectedId={selectedId} expanded={expanded} onToggle={toggle} onSelect={onSelect} />
      ))}
    </div>
  );
}

function TreeNode({
  node,
  depth,
  selectedId,
  expanded,
  onToggle,
  onSelect
}: {
  node: ArtifactTreeNode;
  depth: number;
  selectedId?: string;
  expanded: Set<string>;
  onToggle: (nodeId: string) => void;
  onSelect: (node: ArtifactTreeNode) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isExpanded = expanded.has(node.id);
  const selected = selectedId === node.id;

  return (
    <div role="treeitem" aria-expanded={hasChildren ? isExpanded : undefined} aria-selected={selected}>
      <div className={`tree-row ${selected ? "selected" : ""}`} style={{ paddingLeft: `${depth * 14 + 8}px` }}>
        <button
          type="button"
          className="tree-toggle"
          aria-label={`${isExpanded ? "折叠" : "展开"} ${node.label}`}
          disabled={!hasChildren}
          onClick={() => onToggle(node.id)}
        >
          {hasChildren ? isExpanded ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" /> : null}
        </button>
        <button type="button" className="tree-label-button" onClick={() => onSelect(node)}>
          <span>{node.label}</span>
          {node.badge ? <em>{node.badge}</em> : null}
        </button>
      </div>
      {hasChildren && isExpanded ? (
        <div role="group">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function collectExpandableIds(nodes: ArtifactTreeNode[]): Set<string> {
  const ids = new Set<string>();
  const visit = (items: ArtifactTreeNode[]) => {
    for (const item of items) {
      if (item.children.length) {
        ids.add(item.id);
        visit(item.children);
      }
    }
  };
  visit(nodes);
  return ids;
}
