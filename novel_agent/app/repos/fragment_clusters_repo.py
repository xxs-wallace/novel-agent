from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from novel_agent.app.schemas.creative_kb_schema import FragmentCluster


class FragmentClustersRepo:
    def upsert_clusters(self, conn: sqlite3.Connection, clusters: list[FragmentCluster]) -> None:
        if not clusters:
            return
        now = _utc_now()
        for cluster in clusters:
            conn.execute(
                '''
                INSERT INTO fragment_clusters(
                    cluster_id, cluster_theme, representative_fragment_id,
                    member_count, dedup_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    cluster_theme = excluded.cluster_theme,
                    representative_fragment_id = excluded.representative_fragment_id,
                    member_count = excluded.member_count,
                    dedup_reason = excluded.dedup_reason,
                    updated_at = excluded.updated_at
                ''',
                (
                    cluster.cluster_id,
                    cluster.cluster_theme,
                    cluster.representative_fragment_id,
                    int(cluster.member_count),
                    cluster.dedup_reason,
                    now,
                    now,
                ),
            )

    def get(self, conn: sqlite3.Connection, *, cluster_id: str) -> FragmentCluster | None:
        row = conn.execute(
            'SELECT * FROM fragment_clusters WHERE cluster_id = ?',
            (cluster_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_cluster(row)

    def list_all(
        self,
        conn: sqlite3.Connection,
    ) -> list[FragmentCluster]:
        rows = conn.execute(
            '''
            SELECT * FROM fragment_clusters
            ORDER BY cluster_id
            '''
        ).fetchall()
        return [self._row_to_cluster(row) for row in rows]

    def list_by_cluster_ids(
        self,
        conn: sqlite3.Connection,
        *,
        cluster_ids: list[str],
    ) -> list[FragmentCluster]:
        if not cluster_ids:
            return []
        placeholders = ','.join('?' for _ in cluster_ids)
        rows = conn.execute(
            f'''
            SELECT * FROM fragment_clusters
            WHERE cluster_id IN ({placeholders})
            ORDER BY cluster_id
            ''',
            cluster_ids,
        ).fetchall()
        return [self._row_to_cluster(row) for row in rows]

    def get_by_representative_fragment_id(
        self,
        conn: sqlite3.Connection,
        *,
        representative_fragment_id: str,
    ) -> FragmentCluster | None:
        row = conn.execute(
            '''
            SELECT * FROM fragment_clusters
            WHERE representative_fragment_id = ?
            LIMIT 1
            ''',
            (representative_fragment_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_cluster(row)

    def get_representative_fragment_id(
        self,
        conn: sqlite3.Connection,
        *,
        cluster_id: str,
    ) -> str | None:
        row = conn.execute(
            '''
            SELECT representative_fragment_id FROM fragment_clusters
            WHERE cluster_id = ?
            ''',
            (cluster_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row['representative_fragment_id'])

    def delete_by_cluster_ids(
        self,
        conn: sqlite3.Connection,
        *,
        cluster_ids: list[str],
    ) -> None:
        if not cluster_ids:
            return
        placeholders = ','.join('?' for _ in cluster_ids)
        conn.execute(
            f'''
            DELETE FROM fragment_clusters
            WHERE cluster_id IN ({placeholders})
            ''',
            cluster_ids,
        )

    def _row_to_cluster(self, row: sqlite3.Row) -> FragmentCluster:
        return FragmentCluster(
            cluster_id=str(row['cluster_id']),
            cluster_theme=str(row['cluster_theme']),
            representative_fragment_id=str(row['representative_fragment_id']),
            member_count=int(row['member_count']),
            dedup_reason=str(row['dedup_reason']),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
