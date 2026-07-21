import { useState } from "react";
import type { Group } from "../types";

export interface GroupSidebarProps {
  groups: Group[];
  selected: string | null; // null=all, "__unassigned__"=unassigned, else groupId
  onSelect: (value: string | null) => void;
  onCreate: (name: string) => void | Promise<void>;
  onDelete: (groupId: string) => void | Promise<void>;
}

const ALL = "__all__";
const UNASSIGNED = "__unassigned__";

export function GroupSidebar({
  groups,
  selected,
  onSelect,
  onCreate,
  onDelete,
}: GroupSidebarProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setCreating(false);
      return;
    }
    await onCreate(trimmed);
    setName("");
    setCreating(false);
  };

  const selKey = selected === null ? ALL : selected;

  const row = (
    key: string,
    label: string,
    value: string | null,
    trailing?: React.ReactNode,
  ) => {
    const active = selKey === key;
    return (
      <div
        key={key}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "9px 12px",
          borderRadius: 10,
          background: active ? "var(--grad-soft)" : "transparent",
          border: `1px solid ${active ? "var(--border-strong)" : "transparent"}`,
          cursor: "pointer",
          transition: "background var(--dur) var(--ease)",
        }}
        onClick={() => onSelect(value)}
      >
        <span
          style={{
            flex: 1,
            fontSize: 14,
            fontWeight: active ? 600 : 500,
            color: active ? "var(--text)" : "var(--text-dim)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
        {trailing}
      </div>
    );
  };

  return (
    <aside
      style={{
        width: 240,
        flexShrink: 0,
        padding: 14,
        borderRadius: 18,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        backdropFilter: "blur(20px) saturate(140%)",
        WebkitBackdropFilter: "blur(20px) saturate(140%)",
        boxShadow: "var(--shadow-md)",
        alignSelf: "flex-start",
        position: "sticky",
        top: 24,
        display: "grid",
        gap: 4,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "6px 12px 10px",
        }}
      >
        <span
          style={{
            flex: 1,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
          }}
        >
          그룹
        </span>
        <button
          className="btn-ghost"
          onClick={() => setCreating((c) => !c)}
          style={{ padding: "4px 10px", fontSize: 13, lineHeight: 1 }}
          title="그룹 추가"
        >
          +
        </button>
      </div>

      {creating && (
        <div style={{ padding: "0 4px 8px" }}>
          <input
            autoFocus
            placeholder="그룹 이름"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
              else if (e.key === "Escape") {
                setName("");
                setCreating(false);
              }
            }}
            onBlur={() => void submit()}
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 10,
              border: "1px solid var(--border-strong)",
              background: "var(--bg-2)",
              color: "var(--text)",
              fontSize: 13,
              outline: "none",
            }}
          />
        </div>
      )}

      {row(ALL, "전체", null)}
      {row(UNASSIGNED, "미분류", UNASSIGNED)}

      {groups.length > 0 && (
        <div
          style={{
            height: 1,
            background: "var(--border)",
            margin: "8px 4px",
          }}
        />
      )}

      {groups.map((g) =>
        row(
          g.groupId,
          g.name,
          g.groupId,
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (
                confirm(
                  `그룹 "${g.name}"을(를) 삭제할까요? 소속 덱은 미분류로 이동합니다.`,
                )
              ) {
                void onDelete(g.groupId);
              }
            }}
            title="그룹 삭제"
            style={{
              padding: "2px 8px",
              borderRadius: 6,
              border: "1px solid transparent",
              background: "transparent",
              color: "var(--text-muted)",
              fontSize: 14,
              lineHeight: 1,
              cursor: "pointer",
            }}
          >
            ×
          </button>,
        ),
      )}
    </aside>
  );
}
