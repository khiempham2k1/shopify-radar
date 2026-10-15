"use client";

import { useEffect, useMemo, useState } from "react";
import { api, errorText, useApi } from "@/lib/api";
import { fmtNumber, KIND } from "@/lib/format";
import type { Item, ItemList, Source, Tag } from "@/lib/types";
import { FeedRow } from "../ItemRows";
import { notifyChanged, useToast } from "../Providers";
import { Empty, ErrorBox, Loading } from "../States";

const PAGE = 30;
const MODES = [
  { key: "new", label: "Mới", hint: "trong 6 giờ qua" },
  { key: "hot", label: "Đang nổi", hint: "điểm cao trong 48 giờ qua" },
  { key: "today", label: "Hôm nay", hint: "từ 0 giờ hôm nay" },
  { key: "week", label: "Tuần này", hint: "trong 7 ngày qua" },
  { key: "all", label: "Tất cả", hint: "trong 60 ngày qua" },
] as const;
type Mode = (typeof MODES)[number]["key"];

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function FeedView() {
  const toast = useToast();
  const sources = useApi<Source[]>("sources");
  const tags = useApi<Tag[]>("tags");
  const [mode, setMode] = useState<Mode>("week");
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 350);
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("");
  const [sentiment, setSentiment] = useState("");

  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const baseQuery = useMemo(() => {
    const p = new URLSearchParams({ view: "feed", mode, limit: String(PAGE) });
    if (q) p.set("q", q);
    if (source) p.set("source", source);
    if (tag) p.set("tag", tag);
    if (sentiment) p.set("sentiment", sentiment);
    return p.toString();
  }, [mode, q, source, tag, sentiment]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api<ItemList>(`items?${baseQuery}&offset=0`, "GET", undefined, ctrl.signal)
      .then((d) => {
        setItems(d.items);
        setTotal(d.total);
        setLoading(false);
      })
      .catch((err) => {
        if ((err as Error).name === "AbortError") return;
        setError(errorText(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [baseQuery, tick]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const d = await api<ItemList>(`items?${baseQuery}&offset=${items.length}`);
      setItems((prev) => [...prev, ...d.items.filter((i) => !prev.some((p) => p.id === i.id))]);
      setTotal(d.total);
    } catch (err) {
      toast(`Không tải thêm được: ${errorText(err)}`, { tone: "error" });
    } finally {
      setLoadingMore(false);
    }
  }

  async function dismiss(item: Item) {
    const index = items.findIndex((i) => i.id === item.id);
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    setTotal((t) => Math.max(0, t - 1));
    try {
      await api<Item>(`items/${item.id}`, "PATCH", { status: "dismissed" });
      notifyChanged();
    } catch (err) {
      setItems((prev) => insertAt(prev, item, index));
      setTotal((t) => t + 1);
      toast(`Không ẩn được: ${errorText(err)}`, { tone: "error" });
      return;
    }
    toast("Đã ẩn. AI sẽ dùng phản hồi này để lọc tốt hơn.", {
      undo: async () => {
        try {
          const restored = await api<Item>(`items/${item.id}`, "PATCH", { status: "new" });
          setItems((prev) => insertAt(prev, restored, index));
          setTotal((t) => t + 1);
          notifyChanged();
          toast("Đã hiện lại item.");
        } catch (err) {
          toast(`Không hoàn tác được: ${errorText(err)}`, { tone: "error" });
        }
      },
    });
  }

  const feedSources = (sources.data ?? []).filter((s) => s.kind !== "platform");
  const filtered = Boolean(q || source || tag || sentiment);
  const modeInfo = MODES.find((m) => m.key === mode)!;

  return (
    <>
      <div className="top">
        <div>
          <h1>Feed</h1>
          <p>
            Reddit, Shopify Community, X, YouTube, web search và Hacker News, đã lọc và chấm điểm. Video YouTube lấy nội dung từ phụ đề, hoặc Groq khi
            không có phụ đề, rồi tóm tắt.
          </p>
        </div>
      </div>

      <div className="filters">
        <div className="filters" role="group" aria-label="Chế độ xem">
          {MODES.map((m) => (
            <button key={m.key} type="button" className="chip" aria-pressed={mode === m.key} title={m.hint} onClick={() => setMode(m.key)}>
              {m.label}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <input
          className="field search"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Tìm trong tiêu đề, tóm tắt và nội dung video"
          aria-label="Tìm kiếm"
        />
        <select className="field" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Nguồn">
          <option value="">Tất cả nguồn</option>
          {(["social", "web"] as const).map((kind) => {
            const list = feedSources.filter((s) => s.kind === kind);
            return list.length ? (
              <optgroup key={kind} label={KIND[kind]}>
                {list.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                    {s.enabled ? "" : " (tắt)"}
                  </option>
                ))}
              </optgroup>
            ) : null;
          })}
        </select>
        <select className="field" value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Tag">
          <option value="">Mọi tag</option>
          {(tags.data ?? []).map((t) => (
            <option key={t.id} value={String(t.id)}>
              {t.name}
            </option>
          ))}
        </select>
        <select className="field" value={sentiment} onChange={(e) => setSentiment(e.target.value)} aria-label="Cảm xúc">
          <option value="">Mọi cảm xúc</option>
          <option value="neg">Tiêu cực</option>
          <option value="neu">Trung tính</option>
          <option value="pos">Tích cực</option>
        </select>
      </div>

      <div className="panel">
        {error && <ErrorBox error={error} onRetry={() => setTick((t) => t + 1)} />}
        {loading ? (
          <Loading />
        ) : !error && items.length === 0 ? (
          <Empty>
            {filtered
              ? "Không có item nào khớp bộ lọc."
              : `Không có item nào ở chế độ “${modeInfo.label}” (${modeInfo.hint}).`}
          </Empty>
        ) : (
          <div className="list">
            {items.map((item) => (
              <FeedRow key={item.id} item={item} onDismiss={dismiss} />
            ))}
          </div>
        )}
        {!loading && items.length > 0 && (
          <div className="more">
            <span>
              Đang hiện {fmtNumber(items.length)} / {fmtNumber(total)} item · xếp theo điểm
            </span>
            {items.length < total && (
              <button type="button" className="btn" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Đang tải…" : "Tải thêm"}
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function insertAt(list: Item[], item: Item, index: number): Item[] {
  if (list.some((i) => i.id === item.id)) return list;
  const at = index < 0 ? list.length : Math.min(index, list.length);
  return [...list.slice(0, at), item, ...list.slice(at)];
}
