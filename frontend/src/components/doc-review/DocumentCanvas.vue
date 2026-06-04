<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

type DocumentBlock = {
  id: string;
  type: string;
  text: string;
  order?: number;
  meta?: Record<string, any>;
  runs?: DocumentRun[];
  table?: {
    rows?: Array<{
      cells?: Array<{
        text?: string;
        runs?: DocumentRun[];
      }>;
    }>;
  };
};

type DocumentRun = {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  superscript?: boolean;
  subscript?: boolean;
  color?: string;
  highlight?: string;
  font_size?: number;
  font_name?: string;
};

type ThreadMarker = {
  thread_id: string;
  block_id: string;
  selected_text?: string | null;
  char_start?: number | null;
  char_end?: number | null;
  status: "open" | "resolved" | "closed";
  message_count: number;
};

type OpenAccent = {
  bg: string;
  underline: string;
  selectedBg: string;
  badgeA: string;
  badgeB: string;
  blockBg: string;
  blockBorder: string;
};

type RenderRun = DocumentRun & {
  start: number;
  end: number;
};

type RunSlice = {
  text: string;
  tone: "none" | "open" | "resolved";
  selected: boolean;
  accent?: OpenAccent;
};

type MarkerRange = {
  threadId: string;
  start: number;
  end: number;
  status: "open" | "resolved" | "closed";
  selected: boolean;
  accent?: OpenAccent;
};

const props = defineProps<{
  blocks: DocumentBlock[];
  markersByBlock: Record<string, ThreadMarker[]>;
  selectedThreadId?: string;
  inlineReviewEnabled?: boolean;
}>();

const { t } = useI18n();

type RenderBlock = DocumentBlock & {
  renderKind: "heading" | "paragraph" | "list_item" | "toc_entry" | "table";
  displayText: string;
  headingLevel: number;
  listMarker: string;
  listLevel: number;
  inlineRuns: RenderRun[];
  tableRows: Array<{
    cells: Array<{
      text: string;
      runs: RenderRun[];
    }>;
  }>;
};

const emit = defineEmits<{
  "open-thread": [threadId: string];
  "select-range": [
    {
      block_id: string;
      selected_text: string;
      char_start?: number;
      char_end?: number;
      anchor: { top: number; left: number };
    },
  ];
  "clear-selection": [];
}>();

const hasBlocks = computed(() => props.blocks.length > 0);

const OPEN_ACCENT_PALETTE = [
  {
    bg: "rgba(245, 158, 11, 0.32)",
    underline: "rgba(194, 65, 12, 0.58)",
    selectedBg: "rgba(251, 146, 60, 0.46)",
    badgeA: "#fb923c",
    badgeB: "#f97316",
    blockBg: "rgba(249, 115, 22, 0.13)",
    blockBorder: "rgba(194, 65, 12, 0.2)",
  },
  {
    bg: "rgba(236, 72, 153, 0.27)",
    underline: "rgba(157, 23, 77, 0.56)",
    selectedBg: "rgba(244, 114, 182, 0.4)",
    badgeA: "#f472b6",
    badgeB: "#ec4899",
    blockBg: "rgba(236, 72, 153, 0.12)",
    blockBorder: "rgba(157, 23, 77, 0.22)",
  },
  {
    bg: "rgba(59, 130, 246, 0.25)",
    underline: "rgba(30, 64, 175, 0.54)",
    selectedBg: "rgba(96, 165, 250, 0.37)",
    badgeA: "#60a5fa",
    badgeB: "#2563eb",
    blockBg: "rgba(37, 99, 235, 0.12)",
    blockBorder: "rgba(30, 64, 175, 0.22)",
  },
  {
    bg: "rgba(34, 197, 94, 0.24)",
    underline: "rgba(21, 128, 61, 0.53)",
    selectedBg: "rgba(74, 222, 128, 0.37)",
    badgeA: "#4ade80",
    badgeB: "#22c55e",
    blockBg: "rgba(34, 197, 94, 0.12)",
    blockBorder: "rgba(21, 128, 61, 0.21)",
  },
  {
    bg: "rgba(168, 85, 247, 0.24)",
    underline: "rgba(107, 33, 168, 0.52)",
    selectedBg: "rgba(192, 132, 252, 0.36)",
    badgeA: "#c084fc",
    badgeB: "#a855f7",
    blockBg: "rgba(168, 85, 247, 0.12)",
    blockBorder: "rgba(107, 33, 168, 0.22)",
  },
  {
    bg: "rgba(239, 68, 68, 0.25)",
    underline: "rgba(153, 27, 27, 0.54)",
    selectedBg: "rgba(248, 113, 113, 0.37)",
    badgeA: "#f87171",
    badgeB: "#ef4444",
    blockBg: "rgba(239, 68, 68, 0.12)",
    blockBorder: "rgba(153, 27, 27, 0.22)",
  },
  {
    bg: "rgba(6, 182, 212, 0.24)",
    underline: "rgba(14, 116, 144, 0.53)",
    selectedBg: "rgba(34, 211, 238, 0.36)",
    badgeA: "#22d3ee",
    badgeB: "#06b6d4",
    blockBg: "rgba(6, 182, 212, 0.12)",
    blockBorder: "rgba(14, 116, 144, 0.22)",
  },
  {
    bg: "rgba(132, 204, 22, 0.24)",
    underline: "rgba(77, 124, 15, 0.52)",
    selectedBg: "rgba(163, 230, 53, 0.36)",
    badgeA: "#a3e635",
    badgeB: "#84cc16",
    blockBg: "rgba(132, 204, 22, 0.12)",
    blockBorder: "rgba(77, 124, 15, 0.22)",
  },
  {
    bg: "rgba(20, 184, 166, 0.24)",
    underline: "rgba(15, 118, 110, 0.54)",
    selectedBg: "rgba(45, 212, 191, 0.36)",
    badgeA: "#2dd4bf",
    badgeB: "#14b8a6",
    blockBg: "rgba(20, 184, 166, 0.12)",
    blockBorder: "rgba(15, 118, 110, 0.22)",
  },
  {
    bg: "rgba(244, 63, 94, 0.24)",
    underline: "rgba(159, 18, 57, 0.54)",
    selectedBg: "rgba(251, 113, 133, 0.36)",
    badgeA: "#fb7185",
    badgeB: "#f43f5e",
    blockBg: "rgba(244, 63, 94, 0.12)",
    blockBorder: "rgba(159, 18, 57, 0.22)",
  },
  {
    bg: "rgba(251, 146, 60, 0.25)",
    underline: "rgba(154, 52, 18, 0.54)",
    selectedBg: "rgba(253, 186, 116, 0.37)",
    badgeA: "#fdba74",
    badgeB: "#fb923c",
    blockBg: "rgba(251, 146, 60, 0.12)",
    blockBorder: "rgba(154, 52, 18, 0.22)",
  },
  {
    bg: "rgba(129, 140, 248, 0.24)",
    underline: "rgba(67, 56, 202, 0.54)",
    selectedBg: "rgba(165, 180, 252, 0.36)",
    badgeA: "#a5b4fc",
    badgeB: "#818cf8",
    blockBg: "rgba(129, 140, 248, 0.12)",
    blockBorder: "rgba(67, 56, 202, 0.22)",
  },
] as const satisfies ReadonlyArray<OpenAccent>;

const accentByOrder = (index: number): OpenAccent => {
  const direct = OPEN_ACCENT_PALETTE[index];
  if (direct) return direct;
  const hue = Math.round((index * 137.508) % 360);
  return {
    bg: `hsla(${hue}, 84%, 56%, 0.24)`,
    underline: `hsla(${hue}, 72%, 34%, 0.54)`,
    selectedBg: `hsla(${hue}, 88%, 62%, 0.36)`,
    badgeA: `hsl(${hue}, 88%, 62%)`,
    badgeB: `hsl(${(hue + 24) % 360}, 82%, 50%)`,
    blockBg: `hsla(${hue}, 86%, 58%, 0.12)`,
    blockBorder: `hsla(${hue}, 72%, 36%, 0.22)`,
  };
};

const openThreadAccentMap = computed<Record<string, OpenAccent>>(() => {
  const openThreadIds = Array.from(
    new Set(
      Object.values(props.markersByBlock)
        .flat()
        .filter((marker) => marker.status === "open")
        .map((marker) => marker.thread_id),
    ),
  ).sort();
  const map: Record<string, OpenAccent> = {};
  openThreadIds.forEach((threadId, index) => {
    map[threadId] = accentByOrder(index);
  });
  return map;
});

const openAccentByThread = (threadId: string): OpenAccent =>
  openThreadAccentMap.value[threadId] || accentByOrder(0);

const toNumber = (value: unknown, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

const inferListFromText = (
  text: string,
): { marker: string; content: string; level: number } | null => {
  const bulletMatch = text.match(/^([•·▪◦‣\-*+])\s*(.+)$/);
  if (bulletMatch) {
    return {
      marker: bulletMatch[1],
      content: bulletMatch[2],
      level: 0,
    };
  }

  const orderedMatch = text.match(/^(\d+[.)、])\s*(.+)$/);
  if (orderedMatch) {
    return {
      marker: orderedMatch[1],
      content: orderedMatch[2],
      level: 0,
    };
  }

  return null;
};

const inferHeadingLevelFromText = (text: string): number | null => {
  if (!text || text.length > 90) return null;

  const decimalHeading = text.match(
    /^(\d+(?:\.\d+){0,5})(?:[、.．。])?\s*([^\d\s].+)$/,
  );
  if (decimalHeading) {
    const depth = decimalHeading[1].split(".").length;
    return clamp(depth + 1, 2, 6);
  }

  const zhHeading = text.match(
    /^([一二三四五六七八九十百零]{1,6})[、.．。]\s*(.+)$/,
  );
  if (zhHeading) {
    return 2;
  }

  return null;
};

const inferHeadingLevelFromStyle = (style: string): number | null => {
  const normalized = style.trim().toLowerCase();
  if (!normalized) return null;

  if (normalized.includes("title")) return 1;
  if (normalized.includes("subtitle")) return 2;

  const headingMatch = normalized.match(/heading\s*([1-6])/);
  if (headingMatch) {
    return clamp(toNumber(headingMatch[1], 2), 1, 6);
  }

  return null;
};

const normalizeRuns = (runs: unknown, fallbackText: string): DocumentRun[] => {
  const source = Array.isArray(runs) ? runs : [];
  const normalized = source
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const text = String((item as any).text ?? "");
      if (!text) return null;
      return {
        text,
        bold: Boolean((item as any).bold),
        italic: Boolean((item as any).italic),
        underline: Boolean((item as any).underline),
        strike: Boolean((item as any).strike),
        superscript: Boolean((item as any).superscript),
        subscript: Boolean((item as any).subscript),
        color:
          typeof (item as any).color === "string"
            ? (item as any).color
            : undefined,
        highlight:
          typeof (item as any).highlight === "string"
            ? (item as any).highlight
            : undefined,
        font_size: Number.isFinite(Number((item as any).font_size))
          ? Number((item as any).font_size)
          : undefined,
        font_name:
          typeof (item as any).font_name === "string"
            ? (item as any).font_name
            : undefined,
      } as DocumentRun;
    })
    .filter(Boolean) as DocumentRun[];

  if (normalized.length > 0) return normalized;
  return [{ text: fallbackText || "" }];
};

const normalizeTableRows = (table: DocumentBlock["table"]) => {
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  return rows.map((row) => {
    const cells = Array.isArray(row?.cells) ? row.cells : [];
    return {
      cells: cells.map((cell) => {
        const text = String(cell?.text || "");
        return {
          text,
          runs: withRunBounds(normalizeRuns(cell?.runs, text)),
        };
      }),
    };
  });
};

const withRunBounds = (runs: DocumentRun[]): RenderRun[] => {
  let cursor = 0;
  return runs.map((run) => {
    const text = String(run.text || "");
    const start = cursor;
    cursor += text.length;
    return {
      ...run,
      text,
      start,
      end: cursor,
    };
  });
};

const renderBlocks = computed<RenderBlock[]>(() => {
  return props.blocks.map((block) => {
    const rawText = String(block.text || "");
    const inferText = rawText.trim();
    const meta = block.meta || {};
    const styleLevel = inferHeadingLevelFromStyle(String(meta.style || ""));
    const runs = withRunBounds(normalizeRuns(block.runs, rawText));
    const tableRows = normalizeTableRows(block.table);

    if (block.type === "table") {
      return {
        ...block,
        renderKind: "table",
        displayText: rawText,
        headingLevel: 0,
        listMarker: "",
        listLevel: 0,
        inlineRuns: runs,
        tableRows,
      };
    }

    if (block.type === "toc_entry") {
      const level = clamp(toNumber(meta.level, 1), 1, 6);
      return {
        ...block,
        renderKind: "toc_entry",
        displayText: rawText,
        headingLevel: level,
        listMarker: "",
        listLevel: 0,
        inlineRuns: runs,
        tableRows,
      };
    }

    if (block.type === "heading") {
      const level = clamp(toNumber(meta.level, styleLevel || 2), 1, 6);
      return {
        ...block,
        renderKind: "heading",
        displayText: rawText,
        headingLevel: level,
        listMarker: "",
        listLevel: 0,
        inlineRuns: runs,
        tableRows,
      };
    }

    if (block.type === "list_item") {
      const inferred = inferListFromText(inferText);
      const marker = String(meta.marker || inferred?.marker || "•").trim();
      const listLevel = clamp(toNumber(meta.level, inferred?.level ?? 0), 0, 5);
      const listText = inferred?.content || rawText;
      return {
        ...block,
        renderKind: "list_item",
        displayText: listText,
        headingLevel: 0,
        listMarker: marker,
        listLevel,
        inlineRuns: inferred
          ? withRunBounds(normalizeRuns(undefined, listText))
          : runs,
        tableRows,
      };
    }

    if (styleLevel) {
      return {
        ...block,
        renderKind: "heading",
        displayText: rawText,
        headingLevel: styleLevel,
        listMarker: "",
        listLevel: 0,
        inlineRuns: runs,
        tableRows,
      };
    }

    const inferredList = inferListFromText(inferText);
    if (inferredList) {
      return {
        ...block,
        renderKind: "list_item",
        displayText: inferredList.content,
        headingLevel: 0,
        listMarker: inferredList.marker,
        listLevel: inferredList.level,
        inlineRuns: withRunBounds(
          normalizeRuns(undefined, inferredList.content),
        ),
        tableRows,
      };
    }

    const inferredHeading = inferHeadingLevelFromText(inferText);
    if (inferredHeading) {
      return {
        ...block,
        renderKind: "heading",
        displayText: rawText,
        headingLevel: inferredHeading,
        listMarker: "",
        listLevel: 0,
        inlineRuns: runs,
        tableRows,
      };
    }

    return {
      ...block,
      renderKind: "paragraph",
      displayText: rawText,
      headingLevel: 0,
      listMarker: "",
      listLevel: 0,
      inlineRuns: runs,
      tableRows,
    };
  });
});

const normalizeColor = (raw?: string) => {
  if (!raw) return undefined;
  const color = raw.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(color)) return color;
  return undefined;
};

const runStyle = (run: DocumentRun) => {
  const style: Record<string, string> = {};
  const color = normalizeColor(run.color);
  if (color) style.color = color;
  const highlight = normalizeColor(run.highlight);
  if (highlight) style.backgroundColor = highlight;
  if (
    typeof run.font_size === "number" &&
    Number.isFinite(run.font_size) &&
    run.font_size > 0
  ) {
    style.fontSize = `${Math.min(72, Math.max(8, run.font_size))}px`;
  }
  if (run.font_name) {
    style.fontFamily = run.font_name;
  }
  return style;
};

const markerCount = (blockId: string) =>
  (props.markersByBlock[blockId] || []).length;

const markerState = (blockId: string) => {
  const markers = props.markersByBlock[blockId] || [];
  if (markers.some((item) => item.status === "open")) return "open";
  if (markers.some((item) => item.status === "resolved" || item.status === "closed")) return "resolved";
  return "none";
};

const hasSelectedThread = (blockId: string) => {
  if (!props.selectedThreadId) return false;
  return (props.markersByBlock[blockId] || []).some(
    (item) => item.thread_id === props.selectedThreadId,
  );
};

const findOccurrenceIndexes = (text: string, keyword: string): number[] => {
  if (!text || !keyword) return [];
  const points: number[] = [];
  let from = 0;
  while (from < text.length) {
    const idx = text.indexOf(keyword, from);
    if (idx < 0) break;
    points.push(idx);
    from = idx + 1;
  }
  return points;
};

const pickClosestOccurrence = (
  indexes: number[],
  target?: number | null,
): number | undefined => {
  if (!indexes.length) return undefined;
  if (typeof target !== "number" || !Number.isFinite(target)) return indexes[0];
  return indexes.reduce(
    (best, point) =>
      Math.abs(point - target) < Math.abs(best - target) ? point : best,
    indexes[0],
  );
};

const markerRangesByBlock = computed<Record<string, MarkerRange[]>>(() => {
  const map: Record<string, MarkerRange[]> = {};
  for (const block of renderBlocks.value) {
    const blockText = block.inlineRuns.map((run) => run.text).join("");
    const blockLength = blockText.length;
    const markers = props.markersByBlock[block.id] || [];
    const ranges: MarkerRange[] = [];
    for (const marker of markers) {
      let start = Number.isFinite(marker.char_start)
        ? Number(marker.char_start)
        : NaN;
      let end = Number.isFinite(marker.char_end)
        ? Number(marker.char_end)
        : NaN;
      if (!(start >= 0 && end > start && start < blockLength)) {
        const selectedText = String(marker.selected_text || "");
        if (selectedText) {
          const index = pickClosestOccurrence(
            findOccurrenceIndexes(blockText, selectedText),
            Number.isFinite(marker.char_start)
              ? Number(marker.char_start)
              : undefined,
          );
          if (typeof index === "number") {
            start = index;
            end = index + selectedText.length;
          }
        }
      }
      if (!(start >= 0 && end > start)) continue;
      const safeStart = clamp(Math.floor(start), 0, blockLength);
      const safeEnd = clamp(Math.floor(end), safeStart, blockLength);
      if (safeEnd <= safeStart) continue;
      ranges.push({
        threadId: marker.thread_id,
        start: safeStart,
        end: safeEnd,
        status: marker.status,
        selected: marker.thread_id === props.selectedThreadId,
        accent:
          marker.status === "open"
            ? openAccentByThread(marker.thread_id)
            : undefined,
      });
    }
    ranges.sort((a, b) => a.start - b.start || a.end - b.end);
    map[block.id] = ranges;
  }
  return map;
});

const hasPreciseRange = (blockId: string) =>
  (markerRangesByBlock.value[blockId] || []).length > 0;

const blockStateClass = (block: RenderBlock) => {
  if (hasPreciseRange(block.id)) return "state-inline";
  return `state-${markerState(block.id)}`;
};

const resolveSliceTone = (
  activeRanges: MarkerRange[],
): {
  tone: RunSlice["tone"];
  selected: boolean;
  accent?: OpenAccent;
} => {
  if (!activeRanges.length)
    return { tone: "none", selected: false, accent: undefined };
  const selectedOpen = activeRanges.find(
    (range) => range.selected && range.status === "open",
  );
  if (selectedOpen)
    return { tone: "open", selected: true, accent: selectedOpen.accent };
  const selectedResolved = activeRanges.find(
    (range) =>
      range.selected &&
      (range.status === "resolved" || range.status === "closed"),
  );
  if (selectedResolved)
    return { tone: "resolved", selected: true, accent: undefined };
  const firstOpen = activeRanges.find((range) => range.status === "open");
  if (firstOpen)
    return { tone: "open", selected: false, accent: firstOpen.accent };
  if (
    activeRanges.some(
      (range) => range.status === "resolved" || range.status === "closed",
    )
  )
    return { tone: "resolved", selected: false, accent: undefined };
  return { tone: "none", selected: false, accent: undefined };
};

const sliceRun = (run: RenderRun, ranges: MarkerRange[]): RunSlice[] => {
  const runText = String(run.text || "");
  if (!runText) return [];
  if (!ranges.length) {
    return [{ text: runText, tone: "none", selected: false }];
  }
  const boundaries = new Set<number>([run.start, run.end]);
  for (const range of ranges) {
    if (range.end <= run.start || range.start >= run.end) continue;
    boundaries.add(clamp(range.start, run.start, run.end));
    boundaries.add(clamp(range.end, run.start, run.end));
  }
  const points = Array.from(boundaries).sort((a, b) => a - b);
  const slices: RunSlice[] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const segStart = points[i];
    const segEnd = points[i + 1];
    if (segEnd <= segStart) continue;
    const text = runText.slice(segStart - run.start, segEnd - run.start);
    if (!text) continue;
    const activeRanges = ranges.filter(
      (range) => range.start < segEnd && range.end > segStart,
    );
    const state = resolveSliceTone(activeRanges);
    const prev = slices[slices.length - 1];
    if (
      prev &&
      prev.tone === state.tone &&
      prev.selected === state.selected &&
      prev.accent?.badgeA === state.accent?.badgeA
    ) {
      prev.text += text;
    } else {
      slices.push({
        text,
        tone: state.tone,
        selected: state.selected,
        accent: state.accent,
      });
    }
  }
  return slices.length
    ? slices
    : [{ text: runText, tone: "none", selected: false, accent: undefined }];
};

const runSlices = (block: RenderBlock, run: RenderRun): RunSlice[] =>
  sliceRun(run, markerRangesByBlock.value[block.id] || []);

const fragmentStyle = (piece: RunSlice) => {
  if (piece.tone !== "open") return undefined;
  const accent = piece.accent || accentByOrder(0);
  return {
    "--open-bg": accent.bg,
    "--open-underline": accent.underline,
    "--open-selected-bg": accent.selectedBg,
  } as Record<string, string>;
};

const openThreadIdsForBlock = (blockId: string): string[] => {
  const openIds = new Set<string>();
  for (const marker of props.markersByBlock[blockId] || []) {
    if (marker.status === "open") {
      openIds.add(marker.thread_id);
    }
  }
  return Array.from(openIds);
};

const primaryOpenThreadId = (blockId: string): string | null => {
  const markers = props.markersByBlock[blockId] || [];
  if (!markers.length) return null;
  if (props.selectedThreadId) {
    const selectedOpen = markers.find(
      (item) =>
        item.thread_id === props.selectedThreadId && item.status === "open",
    );
    if (selectedOpen) return selectedOpen.thread_id;
  }
  const firstOpen = markers.find((item) => item.status === "open");
  return firstOpen?.thread_id || null;
};

const blockStyle = (block: RenderBlock): Record<string, string> | undefined => {
  const style: Record<string, string> = {};
  if (block.renderKind === "list_item") {
    style["--list-indent"] = `${block.listLevel * 22}px`;
  }
  if (markerState(block.id) === "open" && !hasPreciseRange(block.id)) {
    const threadId = primaryOpenThreadId(block.id);
    if (threadId) {
      const accent = openAccentByThread(threadId);
      style["--block-open-bg"] = accent.blockBg;
      style["--block-open-border"] = accent.blockBorder;
    }
  }
  return Object.keys(style).length ? style : undefined;
};

const badgeStyle = (blockId: string): Record<string, string> | undefined => {
  const openIds = openThreadIdsForBlock(blockId);
  if (!openIds.length) return undefined;
  const accents = openIds.map((threadId) => openAccentByThread(threadId));
  if (accents.length === 1) {
    return {
      "--badge-bg": `linear-gradient(180deg, ${accents[0].badgeA}, ${accents[0].badgeB})`,
      "--badge-shadow": `0 4px 12px ${accents[0].blockBorder}, 0 0 0 2px rgba(255, 255, 255, 0.9)`,
    };
  }

  const segment = 360 / accents.length;
  const gradientStops = accents
    .map((accent, index) => {
      const start = Math.round(index * segment);
      const end = Math.round((index + 1) * segment);
      return `${accent.badgeA} ${start}deg ${end}deg`;
    })
    .join(", ");

  return {
    "--badge-bg": `conic-gradient(${gradientStops})`,
    "--badge-shadow":
      "0 4px 12px rgba(15, 23, 42, 0.28), 0 0 0 2px rgba(255, 255, 255, 0.9)",
  };
};

const openBlockThread = (blockId: string) => {
  const markers = props.markersByBlock[blockId] || [];
  if (!markers.length) return;
  const preferred =
    markers.find((item) => item.status === "open") || markers[0];
  emit("open-thread", preferred.thread_id);
};

const emitSelection = (event: MouseEvent, block: RenderBlock) => {
  if (!props.inlineReviewEnabled) return;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    emit("clear-selection");
    return;
  }
  const range = selection.getRangeAt(0);
  const selectedText = selection.toString().trim();
  if (!selectedText) {
    emit("clear-selection");
    return;
  }
  const blockElement = (event.currentTarget as HTMLElement) || null;
  if (!blockElement) {
    emit("clear-selection");
    return;
  }
  const selectionRoot =
    (blockElement.querySelector(".doc-select-root") as HTMLElement) ||
    blockElement;
  if (
    !selectionRoot.contains(range.startContainer) ||
    !selectionRoot.contains(range.endContainer)
  ) {
    emit("clear-selection");
    return;
  }

  const beforeRange = range.cloneRange();
  beforeRange.selectNodeContents(selectionRoot);
  beforeRange.setEnd(range.startContainer, range.startOffset);
  const rawSelected = range.toString();
  const leadingWhitespaceLength = rawSelected.match(/^\s*/)?.[0]?.length || 0;
  const trailingWhitespaceLength = rawSelected.match(/\s*$/)?.[0]?.length || 0;
  const contentLength = block.inlineRuns.reduce(
    (sum, run) => sum + run.text.length,
    0,
  );
  const startRaw = beforeRange.toString().length + leadingWhitespaceLength;
  const endRaw =
    beforeRange.toString().length +
    rawSelected.length -
    trailingWhitespaceLength;
  const charStart = clamp(startRaw, 0, contentLength);
  const charEnd = clamp(Math.max(endRaw, charStart), charStart, contentLength);
  const rect = range.getBoundingClientRect();
  emit("select-range", {
    block_id: block.id,
    selected_text: selectedText,
    char_start: charStart,
    char_end: charEnd,
    anchor: {
      top: rect.bottom,
      left: rect.left,
    },
  });
};
</script>

<template>
  <div class="doc-canvas">
    <div v-if="!hasBlocks" class="doc-empty glass-panel">
      {{ t("doc_review.no_renderable_blocks") }}
    </div>
    <div v-else class="doc-paper">
      <article
        v-for="block in renderBlocks"
        :key="block.id"
        class="doc-block"
        :class="[
          `kind-${block.renderKind}`,
          blockStateClass(block),
          { 'is-selected-thread': hasSelectedThread(block.id) },
          block.renderKind === 'heading'
            ? `heading-level-${block.headingLevel}`
            : '',
        ]"
        :style="blockStyle(block)"
        @mouseup="emitSelection($event, block)"
      >
        <button
          v-if="markerCount(block.id) > 0"
          class="thread-badge"
          :class="`state-${markerState(block.id)}`"
          :style="badgeStyle(block.id)"
          @click.stop="openBlockThread(block.id)"
        >
          {{ markerCount(block.id) }}
        </button>

        <component
          :is="`h${block.headingLevel}`"
          v-if="block.renderKind === 'heading'"
          class="doc-heading doc-select-root"
        >
          <span
            v-for="(run, runIndex) in block.inlineRuns"
            :key="`${block.id}-head-${runIndex}`"
            class="doc-run"
            :class="{
              bold: run.bold,
              italic: run.italic,
              underline: run.underline,
              strike: run.strike,
              superscript: run.superscript,
              subscript: run.subscript,
            }"
            :style="runStyle(run)"
          >
            <span
              v-for="(piece, pieceIndex) in runSlices(block, run)"
              :key="`${block.id}-head-${runIndex}-piece-${pieceIndex}`"
              class="doc-fragment"
              :class="[
                piece.tone !== 'none' ? `tone-${piece.tone}` : '',
                { 'is-selected': piece.selected },
              ]"
              :style="fragmentStyle(piece)"
            >
              {{ piece.text }}
            </span>
          </span>
        </component>

        <p v-else-if="block.renderKind === 'list_item'" class="doc-list-item">
          <span class="list-marker">{{ block.listMarker }}</span>
          <span class="list-text doc-select-root">
            <span
              v-for="(run, runIndex) in block.inlineRuns"
              :key="`${block.id}-list-${runIndex}`"
              class="doc-run"
              :class="{
                bold: run.bold,
                italic: run.italic,
                underline: run.underline,
                strike: run.strike,
                superscript: run.superscript,
                subscript: run.subscript,
              }"
              :style="runStyle(run)"
            >
              <span
                v-for="(piece, pieceIndex) in runSlices(block, run)"
                :key="`${block.id}-list-${runIndex}-piece-${pieceIndex}`"
                class="doc-fragment"
                :class="[
                  piece.tone !== 'none' ? `tone-${piece.tone}` : '',
                  { 'is-selected': piece.selected },
                ]"
                :style="fragmentStyle(piece)"
              >
                {{ piece.text }}
              </span>
            </span>
          </span>
        </p>

        <p
          v-else-if="block.renderKind === 'toc_entry'"
          class="doc-toc-entry doc-select-root"
        >
          <span
            v-for="(run, runIndex) in block.inlineRuns"
            :key="`${block.id}-toc-${runIndex}`"
            class="doc-run"
            :class="{
              bold: run.bold,
              italic: run.italic,
              underline: run.underline,
              strike: run.strike,
              superscript: run.superscript,
              subscript: run.subscript,
            }"
            :style="runStyle(run)"
          >
            <span
              v-for="(piece, pieceIndex) in runSlices(block, run)"
              :key="`${block.id}-toc-${runIndex}-piece-${pieceIndex}`"
              class="doc-fragment"
              :class="[
                piece.tone !== 'none' ? `tone-${piece.tone}` : '',
                { 'is-selected': piece.selected },
              ]"
              :style="fragmentStyle(piece)"
            >
              {{ piece.text }}
            </span>
          </span>
        </p>

        <div v-else-if="block.renderKind === 'table'" class="doc-table-wrap">
          <table class="doc-table">
            <tbody>
              <tr
                v-for="(row, rowIndex) in block.tableRows"
                :key="`${block.id}-row-${rowIndex}`"
              >
                <td
                  v-for="(cell, cellIndex) in row.cells"
                  :key="`${block.id}-cell-${rowIndex}-${cellIndex}`"
                >
                  <span
                    v-for="(run, runIndex) in cell.runs"
                    :key="`${block.id}-cellrun-${rowIndex}-${cellIndex}-${runIndex}`"
                    class="doc-run"
                    :class="{
                      bold: run.bold,
                      italic: run.italic,
                      underline: run.underline,
                      strike: run.strike,
                      superscript: run.superscript,
                      subscript: run.subscript,
                    }"
                    :style="runStyle(run)"
                  >
                    {{ run.text }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-else class="doc-paragraph doc-select-root">
          <span
            v-for="(run, runIndex) in block.inlineRuns"
            :key="`${block.id}-p-${runIndex}`"
            class="doc-run"
            :class="{
              bold: run.bold,
              italic: run.italic,
              underline: run.underline,
              strike: run.strike,
              superscript: run.superscript,
              subscript: run.subscript,
            }"
            :style="runStyle(run)"
          >
            <span
              v-for="(piece, pieceIndex) in runSlices(block, run)"
              :key="`${block.id}-p-${runIndex}-piece-${pieceIndex}`"
              class="doc-fragment"
              :class="[
                piece.tone !== 'none' ? `tone-${piece.tone}` : '',
                { 'is-selected': piece.selected },
              ]"
              :style="fragmentStyle(piece)"
            >
              {{ piece.text }}
            </span>
          </span>
        </p>
      </article>
    </div>
  </div>
</template>

<style scoped>
@import url("https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap");

.doc-canvas {
  position: relative;
  min-height: 120px;
}

.doc-empty {
  padding: 18px;
  font-size: 13px;
  color: var(--color-text-muted);
}

.doc-paper {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 48px 60px 80px;
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
  box-shadow:
    0 20px 40px -10px rgba(15, 23, 42, 0.05),
    0 0 0 1px rgba(14, 165, 233, 0.05);
}

.doc-block {
  position: relative;
  margin: 0;
  padding: 2px 6px;
  transition:
    background-color 180ms ease,
    box-shadow 180ms ease;
}

.doc-block + .doc-block {
  margin-top: 8px;
}

.doc-block.kind-heading {
  margin-top: 18px;
}

.doc-block.kind-heading:first-child {
  margin-top: 0;
}

.doc-block.kind-list_item {
  padding-left: calc(var(--list-indent, 0px) + 6px);
}

.doc-block.kind-table {
  margin-top: 12px;
}

.doc-block.state-open {
  border-radius: 8px;
  background: var(--block-open-bg, rgba(249, 115, 22, 0.13));
  box-shadow: inset 0 0 0 1px var(--block-open-border, rgba(194, 65, 12, 0.2));
}

.doc-block.state-resolved {
  border-radius: 8px;
  background: rgba(16, 185, 129, 0.08);
  box-shadow: inset 0 0 0 1px rgba(5, 150, 105, 0.14);
}

.doc-block.state-inline {
  border-radius: 8px;
}

.doc-block.is-selected-thread {
  border-radius: var(--radius-lg);
  box-shadow:
    0 0 20px rgba(14, 165, 233, 0.15),
    inset 0 0 0 1.5px rgba(14, 165, 233, 0.4);
}

.doc-heading {
  margin: 0;
  line-height: 1.45;
  color: var(--color-text-title);
  white-space: pre-wrap;
  font-family: "Plus Jakarta Sans", var(--font-heading), sans-serif;
  letter-spacing: -0.02em;
}

.heading-level-1 .doc-heading {
  font-size: 1.6rem;
}

.heading-level-2 .doc-heading {
  font-size: 1.35rem;
}

.heading-level-3 .doc-heading {
  font-size: 1.18rem;
}

.heading-level-4 .doc-heading {
  font-size: 1.08rem;
}

.heading-level-5 .doc-heading,
.heading-level-6 .doc-heading {
  font-size: 1rem;
}

.doc-paragraph {
  margin: 0;
  font-size: 0.98rem;
  line-height: 1.85;
  color: var(--color-text-body);
  white-space: pre-wrap;
  font-family: "Plus Jakarta Sans", var(--font-body), sans-serif;
}

.doc-toc-entry {
  margin: 0;
  color: #334155;
  font-size: 0.96rem;
  line-height: 1.72;
  white-space: pre-wrap;
  border-left: 2px solid rgba(14, 165, 233, 0.3);
  padding-left: 10px;
  font-family: "Plus Jakarta Sans", var(--font-body), sans-serif;
  transition: all 0.2s;
}

.doc-toc-entry:hover {
  border-left-color: rgba(14, 165, 233, 0.8);
  background: linear-gradient(
    90deg,
    rgba(14, 165, 233, 0.05) 0%,
    transparent 100%
  );
}

.doc-list-item {
  margin: 0;
  display: flex;
  align-items: flex-start;
  font-size: 0.98rem;
  line-height: 1.8;
  color: var(--color-text-body);
  font-family: "Plus Jakarta Sans", var(--font-body), sans-serif;
}

.list-marker {
  width: 2.2em;
  flex: 0 0 2.2em;
  text-align: right;
  color: #334155;
  font-weight: 600;
  padding-right: 0.55em;
}

.list-text {
  flex: 1;
  white-space: pre-wrap;
}

.doc-table-wrap {
  overflow-x: auto;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
  border-spacing: 0;
  border: 1px solid rgba(148, 163, 184, 0.38);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
}

.doc-table td {
  border: 1px solid rgba(148, 163, 184, 0.26);
  padding: 8px 10px;
  vertical-align: top;
  font-size: 0.94rem;
  line-height: 1.65;
  color: var(--color-text-body);
  white-space: pre-wrap;
  min-width: 96px;
}

.doc-run.bold {
  font-weight: 700;
}

.doc-run.italic {
  font-style: italic;
}

.doc-run.underline {
  text-decoration: underline;
}

.doc-run.strike {
  text-decoration: line-through;
}

.doc-run.superscript {
  vertical-align: super;
  font-size: 0.8em !important;
}

.doc-run.subscript {
  vertical-align: sub;
  font-size: 0.8em !important;
}

.doc-fragment {
  border-radius: 4px;
  padding: 0 0.08em;
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
  transition:
    background-color 160ms ease,
    box-shadow 160ms ease;
}

.doc-fragment.tone-open {
  background: var(--open-bg, rgba(245, 158, 11, 0.3));
  box-shadow: inset 0 -1px 0 var(--open-underline, rgba(194, 65, 12, 0.52));
}

.doc-fragment.tone-resolved {
  background: rgba(16, 185, 129, 0.18);
  box-shadow: inset 0 -1px 0 rgba(5, 150, 105, 0.36);
}

.doc-fragment.is-selected {
  background: rgba(14, 165, 233, 0.24);
  box-shadow: inset 0 -2px 0 rgba(3, 105, 161, 0.52);
}

.doc-fragment.tone-open.is-selected {
  background: var(--open-selected-bg, rgba(251, 146, 60, 0.42));
}

.doc-fragment.tone-resolved.is-selected {
  background: rgba(52, 211, 153, 0.34);
}

.thread-badge {
  position: absolute;
  top: 2px;
  right: 4px;
  min-width: 22px;
  height: 22px;
  border-radius: 999px;
  border: none;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: #f97316;
  box-shadow:
    0 4px 12px rgba(194, 65, 12, 0.2),
    0 0 0 1.5px rgba(255, 255, 255, 0.9);
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.thread-badge:hover {
  transform: scale(1.15);
}

.thread-badge.state-open {
  background: var(--badge-bg, linear-gradient(135deg, #fb923c, #f97316));
  box-shadow: var(
    --badge-shadow,
    0 4px 12px rgba(194, 65, 12, 0.25),
    0 0 0 1.5px rgba(255, 255, 255, 0.9)
  );
}

.thread-badge.state-resolved {
  background: linear-gradient(135deg, #34d399, #059669);
  box-shadow:
    0 4px 12px rgba(5, 150, 105, 0.25),
    0 0 0 1.5px rgba(255, 255, 255, 0.9);
}

@media (max-width: 960px) {
  .doc-paper {
    padding: 22px 18px 24px;
    border-radius: 10px;
  }

  .thread-badge {
    right: 2px;
  }
}
</style>
