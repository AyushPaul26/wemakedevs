export const newerSnapshot = <
  T extends { generation: number; revision: number },
>(
  current: T | null,
  incoming: T,
): T =>
  !current ||
  incoming.generation > current.generation ||
  (incoming.generation === current.generation &&
    incoming.revision > current.revision)
    ? incoming
    : current;
export const uniqueRefs = <T extends { source_id: string; version_id: string }>(
  refs: T[],
): T[] =>
  refs.filter(
    (item, index) =>
      refs.findIndex(
        (other) =>
          other.source_id === item.source_id &&
          other.version_id === item.version_id,
      ) === index,
  );
export const uniqueEvidenceRefs = <
  T extends { source_id: string; version_id: string; chunk_id: string },
>(
  refs: T[],
): T[] =>
  refs.filter(
    (item, index) =>
      refs.findIndex(
        (other) =>
          other.source_id === item.source_id &&
          other.version_id === item.version_id &&
          other.chunk_id === item.chunk_id,
      ) === index,
  );
